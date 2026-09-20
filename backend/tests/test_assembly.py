import json
import shutil
from types import SimpleNamespace

import pytest

from app.production import assemble, command


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
