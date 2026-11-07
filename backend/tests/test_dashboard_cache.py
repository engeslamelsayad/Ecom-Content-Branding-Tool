import httpx
from fastapi import FastAPI

from app.main import mount_dashboard


async def test_shell_is_revalidated_and_hashed_assets_are_cached_for_good(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'index.html').write_text('<script src="/assets/index-abc123.js"></script>')
    (tmp_path / 'assets' / 'index-abc123.js').write_text('console.log(1)')
    app = FastAPI()
    mount_dashboard(app, tmp_path)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path in ('/', '/library', '/index.html'):  # every route that serves the shell
            response = await client.get(path)
            assert response.status_code == 200 and 'index-abc123.js' in response.text, path
            assert response.headers['cache-control'] == 'no-cache', path

        bundle = await client.get('/assets/index-abc123.js')
        assert bundle.status_code == 200
        assert 'immutable' in bundle.headers['cache-control']

        gone = await client.get('/assets/index-old999.js')  # a bundle from a previous deploy
        assert gone.status_code == 404 and 'immutable' not in gone.headers.get('cache-control', '')
