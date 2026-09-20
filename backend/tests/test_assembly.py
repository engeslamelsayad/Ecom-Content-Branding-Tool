import json
import shutil
from types import SimpleNamespace

import pytest

from app.production import assemble, command, finish_video, captions_ass


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg/ffprobe required; installed in CI and Docker')
async def test_multiscene_assembly_preserves_complete_narration(env, tmp_path):
    video, audio = tmp_path / 'source.mp4', tmp_path / 'voice.mp3'
    await command('ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:d=0.5', '-c:v', 'libx264', str(video))
    await command('ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.5', str(audio))
    job = SimpleNamespace(id='assembly-test', brand_id=env['brand'], inputs={'aspect_ratio': '1:1'}, steps=[
        {'kind': 'video', 'local_path': str(video), 'duration': 0.5},
        {'kind': 'video', 'local_path': str(video), 'duration': 0.5},
        {'kind': 'audio', 'local_path': str(audio)}])
    output = await assemble(job)
    probe = json.loads(await command('ffprobe', '-v', 'quiet', '-show_streams', '-show_format', '-of', 'json', str(output)))
    streams = {s['codec_type']: s for s in probe['streams']}
    assert streams['video']['width'] == streams['video']['height'] == 720
    assert 'audio' in streams
    assert float(probe['format']['duration']) >= 1.5


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
async def test_ugc_assembly_keeps_native_audio_and_burns_arabic_captions(env, tmp_path):
    video = tmp_path / 'speaking.mp4'
    await command('ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:d=1',
                  '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:v', 'libx264', '-c:a', 'aac', str(video))
    transcript = tmp_path / 'transcript.json'
    transcript.write_text(json.dumps({'words': [{'start': 0.1, 'end': 0.7, 'word': 'المنتج'},
                                               {'start': 1.1, 'end': 1.7, 'word': 'تفاصيله'}]}), encoding='utf-8')
    job = SimpleNamespace(id='ugc-assembly', brand_id=env['brand'], inputs={'aspect_ratio': '9:16', 'video_mode': 'ugc'}, steps=[
        {'kind': 'video', 'local_path': str(video), 'duration': 1},
        {'kind': 'video', 'local_path': str(video), 'duration': 1},
        {'kind': 'captions', 'local_path': str(transcript)}])
    output = await finish_video(job)
    probe = json.loads(await command('ffprobe', '-v', 'quiet', '-show_streams', '-show_format', '-of', 'json', str(output)))
    streams = {s['codec_type']: s for s in probe['streams']}
    assert 'audio' in streams and streams['video']['height'] == 1280
    assert float(probe['format']['duration']) >= 1.9
    # Confirm subtitle pixels actually change a frame, rather than only generating a sidecar.
    raw = await command('ffmpeg', '-v', 'error', '-ss', '0.4', '-i', str(output), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')
    assert any(raw[i] > 180 and raw[i+1] > 180 and raw[i+2] > 180 for i in range(0, len(raw) - 2, 3))


def test_caption_timing_and_ass_escape():
    result = captions_ass([{'start': .25, 'end': 1.5, 'word': r'{\pos(0,0)}مرحبا\N'},
                           {'start': 3, 'end': 4, 'word': 'بكم'}], 720, 1280)
    assert '0:00:00.25,0:00:01.50' in result
    assert '\\pos' not in result and '\\N' not in result
    with pytest.raises(ValueError): captions_ass([], 720, 1280)
