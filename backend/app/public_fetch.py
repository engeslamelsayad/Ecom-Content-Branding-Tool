"""Pin browser fetches to validated public IPs, including redirects/subresources."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import aiohttp
from aiohttp.abc import AbstractResolver


class PublicResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        resolved = []
        for fam, _, proto, _, addr in rows:
            ip = ipaddress.ip_address(addr[0])
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise OSError('Private address rejected')
            resolved.append({'hostname': host, 'host': addr[0], 'port': port,
                             'family': fam, 'proto': proto, 'flags': socket.AI_NUMERICHOST})
        return resolved

    async def close(self):
        pass


async def install_public_routes(page):
    count = 0

    async def intercept(route):
        nonlocal count
        count += 1
        request = route.request
        try:
            parsed = urlparse(request.url)
            blocked = (count > 200 or parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443) or request.method != 'GET'
                or request.resource_type in ('media', 'websocket'))
        except ValueError:
            blocked = True
        if blocked:
            await route.abort()
            return
        try:
            # aiohttp bypasses resolvers for literal IPs, so validate those here.
            try:
                literal = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                literal = None
            if literal and (not literal.is_global or literal.is_multicast or literal.is_reserved):
                raise OSError('Private address rejected')
            connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                                             timeout=aiohttp.ClientTimeout(total=25)) as session:
                headers = await request.all_headers()
                headers.pop('host', None)
                async with session.get(request.url, headers=headers, allow_redirects=False) as response:
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > 20 * 1024 * 1024:
                            raise ValueError('Response too large')
                    clean_headers = {k: v for k, v in response.headers.items()
                                     if k.lower() not in ('content-encoding', 'content-length', 'transfer-encoding')}
                    await route.fulfill(status=response.status, headers=clean_headers, body=bytes(data))
        except (OSError, ValueError, aiohttp.ClientError, asyncio.TimeoutError):
            await route.abort()

    await page.route('**/*', intercept)
    await page.route_web_socket('**/*', lambda ws: ws.close())
