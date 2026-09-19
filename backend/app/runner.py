"""Executes a module run in the background and streams it to whoever is watching.

A run outlives the HTTP request that started it: the browser tab can be closed
and reopened, and a 13-module plan keeps writing. Subscribers attach to a live
buffer; late joiners get everything already produced, then follow along.

Single-instance by design -- the buffer lives in this process. Scaling past one
worker would mean moving the broker to Redis; the persisted Run row is already
the durable record either way.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import llm, media, prompting
from .db import SessionLocal
from .models import Brand, Run
from .modules import Module, get_module
from .skill_engine import registry

log = logging.getLogger(__name__)

SCORE_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
SECTION_MARKER = re.compile(r"<!--section:[^>]*-->")


@dataclass
class RunStream:
    chunks: list[dict] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    done: bool = False

    def publish(self, event: dict) -> None:
        self.chunks.append(event)
        for queue in list(self.subscribers):
            queue.put_nowait(event)

    def finish(self) -> None:
        self.done = True
        for queue in list(self.subscribers):
            queue.put_nowait({"type": "end"})


class Broker:
    def __init__(self) -> None:
        self._streams: dict[str, RunStream] = {}

    def open(self, run_id: str) -> RunStream:
        stream = RunStream()
        self._streams[run_id] = stream
        return stream

    def get(self, run_id: str) -> RunStream | None:
        return self._streams.get(run_id)

    def drop(self, run_id: str) -> None:
        self._streams.pop(run_id, None)


broker = Broker()


# ---------------------------------------------------------------------------
# Asset preparation for the review modules
# ---------------------------------------------------------------------------
async def _prepare_assets(module: Module, inputs: dict, brand_id: str,
                          stream: RunStream) -> tuple[list[media.PreparedImage], str]:
    """Returns the images to attach plus any extra text context."""
    if module.kind != "review":
        return [], ""

    if module.key == "review_static":
        path = inputs.get("_image_path")
        if not path:
            raise ValueError("لازم ترفع صورة الإعلان.")
        return [media.prepare_image(media.Path(path), "[STATIC AD CREATIVE]")], ""

    if module.key == "review_video":
        path = inputs.get("_video_path")
        if not path:
            raise ValueError("لازم ترفع ملف الفيديو.")
        stream.publish({"type": "status", "text": "بستخرج فريمات من الفيديو…"})
        frames = await asyncio.to_thread(media.extract_frames, media.Path(path))
        images = media.frames_to_images(frames)
        stamps = ", ".join(f"{ts:.1f}s" for ts, _ in frames)
        extra = f"## Frames supplied\nSampled at: {stamps}\n"
        if transcript := inputs.get("transcript"):
            extra += f"\n## Script / transcript supplied\n{transcript}\n"
        else:
            extra += "\nNo transcript was supplied — judge the visual track only and say so.\n"
        return images, extra

    if module.key == "review_landing":
        url = (inputs.get("url") or "").strip()
        if not url:
            raise ValueError("لازم تحط رابط الصفحة.")
        stream.publish({"type": "status", "text": "بفتح الصفحة وباخد لقطة كاملة…"})
        capture = await media.capture_page(url, brand_id)
        images = await asyncio.to_thread(media.slice_tall_screenshot, capture.screenshot)
        extra = (
            f"## Page captured\n- URL: {capture.final_url}\n- Title: {capture.title}\n\n"
            f"## Extracted page copy\n```\n{capture.text}\n```\n"
        )
        return images, extra

    return [], ""


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
async def execute(run_id: str, model_override: str | None = None) -> None:
    stream = broker.get(run_id) or broker.open(run_id)
    usage_total = llm.Usage()
    collected: list[str] = []
    target_section = ""
    parent_id: str | None = None

    try:
        async with SessionLocal() as db:
            run = await db.get(Run, run_id)
            if run is None:
                raise RuntimeError("run disappeared")
            brand = await db.scalar(
                select(Brand).where(Brand.id == run.brand_id).options(
                    selectinload(Brand.products),
                    selectinload(Brand.avatars),
                    selectinload(Brand.competitors),
                    selectinload(Brand.voc_entries),
                )
            )
            module = get_module(run.module_key)
            inputs = dict(run.inputs or {})
            target_section = run.section_key or ""
            parent_id = run.parent_run_id
            run.status = "running"
            await db.commit()

        images, extra_context = await _prepare_assets(module, inputs, brand.id, stream)

        skill_text = registry.compose(module.skill, list(module.refs))
        context_text = "\n\n".join(filter(None, [
            prompting.OPERATING_RULES,
            prompting.brand_context(brand),
            extra_context,
        ]))
        model = llm.model_for(module.tier, model_override)

        # A multi-section module is a sequence of calls sharing one cached
        # prefix, so each section can later be regenerated on its own.
        sections = list(module.sections) or [("", "")]
        if target_section:
            sections = [s for s in sections if s[0] == target_section]
            if not sections:
                raise RuntimeError(f"unknown section: {target_section}")
        single = len(sections) == 1 and not sections[0][0]

        for index, (section_key, section_title) in enumerate(sections, start=1):
            if not single:
                stream.publish({
                    "type": "section",
                    "key": section_key,
                    "title": section_title,
                    "index": index,
                    "total": len(sections),
                })
                collected.append(f"\n\n<!--section:{section_key}-->\n")

            request = llm.Request(
                skill_text=skill_text,
                context_text=context_text,
                task=prompting.build_task(module, inputs, section_title or None),
                model=model,
                effort=module.effort,
                max_tokens=32000 if single else 16000,
                images=[(i.media_type, i.data) for i in images],
                image_labels=[i.label for i in images],
            )

            async for chunk in llm.stream(request):
                if chunk.kind == "text":
                    collected.append(chunk.text)
                    stream.publish({"type": "text", "text": chunk.text})
                elif chunk.kind == "thinking":
                    stream.publish({"type": "thinking", "text": chunk.text})
                elif chunk.kind == "usage" and chunk.usage:
                    usage_total.add(chunk.usage)
                    stream.publish({
                        "type": "usage",
                        "input": usage_total.input_tokens,
                        "output": usage_total.output_tokens,
                        "cache_read": usage_total.cache_read_tokens,
                        "cost": round(usage_total.cost_usd, 4),
                    })
                elif chunk.kind == "error":
                    raise RuntimeError(chunk.text)

        output = "".join(collected).strip()
        await _persist(run_id, output, usage_total, module, status="done")
        if parent_id and target_section:
            await _splice_into_parent(parent_id, target_section, output)
        stream.publish({"type": "done", "cost": round(usage_total.cost_usd, 4)})

    except Exception as exc:  # surfaced to the user, not swallowed
        log.exception("run %s failed", run_id)
        message = str(exc) or exc.__class__.__name__
        await _persist(run_id, "".join(collected).strip(), usage_total, None,
                       status="error", error=message)
        stream.publish({"type": "error", "text": message})
    finally:
        stream.finish()


async def _persist(run_id: str, output: str, usage: llm.Usage, module: Module | None,
                   status: str, error: str = "") -> None:
    async with SessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.output_md = output
        run.error = error
        run.model = usage.model or run.model
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.cache_read_tokens = usage.cache_read_tokens
        run.cache_write_tokens = usage.cache_write_tokens
        run.cost_usd = round(usage.cost_usd, 6)

        if module and module.kind == "review":
            run.scores = _extract_scores(output)

        # Fold the result back into the Brand Brain so later modules inherit it.
        if status == "done" and module and module.writes_core:
            brand = await db.get(Brand, run.brand_id)
            if brand is not None:
                core = dict(brand.core or {})
                core[module.writes_core] = output
                brand.core = core

        await db.commit()


async def _splice_into_parent(parent_id: str, section_key: str, replacement: str) -> None:
    """Swap one section of a stored plan for its regenerated version.

    Sections are delimited by the `<!--section:key-->` markers written during the
    original run, so the surrounding modules are left untouched.
    """
    async with SessionLocal() as db:
        parent = await db.get(Run, parent_id)
        if parent is None or not parent.output_md:
            return

        # The child run prefixes its own marker; the parent already has one,
        # so strip it or the splice duplicates the delimiter.
        replacement = SECTION_MARKER.sub("", replacement).strip()

        marker = f"<!--section:{section_key}-->"
        start = parent.output_md.find(marker)
        if start == -1:
            parent.output_md = f"{parent.output_md}\n\n{marker}\n{replacement}"
        else:
            body_start = start + len(marker)
            next_marker = parent.output_md.find("<!--section:", body_start)
            end = len(parent.output_md) if next_marker == -1 else next_marker
            parent.output_md = (
                parent.output_md[:body_start] + "\n" + replacement + "\n\n"
                + parent.output_md[end:]
            )
        await db.commit()


def _extract_scores(output: str) -> dict:
    """Reviews end with a JSON scorecard; pull it out for trending."""
    matches = SCORE_BLOCK.findall(output)
    if not matches:
        return {}
    try:
        parsed = json.loads(matches[-1])
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def start(run_id: str, model_override: str | None = None) -> None:
    broker.open(run_id)
    task = asyncio.create_task(execute(run_id, model_override))
    # Hold a reference so the task is not garbage-collected mid-flight.
    _running.add(task)
    task.add_done_callback(_running.discard)


_running: set[asyncio.Task] = set()
