export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path.startsWith('/dtfhn/') || path.startsWith('/dtfravingfinch/')) {
      return handleR2Request(request, env, path);
    }

    return fetch(request);
  },
};

async function handleR2Request(request, env, path) {
  if (request.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Range',
      },
    });
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', {
      status: 405,
      headers: { 'Allow': 'GET, HEAD, OPTIONS' },
    });
  }

  const key = path.slice(1);
  const hasRange = request.headers.has('range');
  const object = await env.R2_BUCKET.get(key, hasRange ? { range: request.headers } : {});

  if (object === null) {
    // Fall through to Pages origin (serves website HTML)
    return fetch(request);
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('etag', object.httpEtag);

  if (!headers.has('content-type')) {
    const ext = key.split('.').pop().toLowerCase();
    const types = {
      mp3: 'audio/mpeg',
      xml: 'application/rss+xml',
      jpg: 'image/jpeg',
      jpeg: 'image/jpeg',
      png: 'image/png',
      json: 'application/json',
      vtt: 'text/vtt',
    };
    if (types[ext]) headers.set('content-type', types[ext]);
  }

  headers.set('cache-control', 'public, max-age=86400, s-maxage=604800');
  headers.set('accept-ranges', 'bytes');
  headers.set('access-control-allow-origin', '*');
  headers.set('access-control-allow-methods', 'GET, HEAD, OPTIONS');
  headers.set('access-control-expose-headers', 'Content-Length, Content-Range, Content-Type');

  if (hasRange && object.range) {
    const r = object.range;
    const total = object.size;
    const start = r.offset || 0;
    const end = r.offset + r.length - 1;
    headers.set('content-range', `bytes ${start}-${end}/${total}`);
    headers.set('content-length', String(r.length));
    return new Response(object.body, { status: 206, headers });
  }

  headers.set('content-length', String(object.size));
  return new Response(object.body, { status: 200, headers });
}
