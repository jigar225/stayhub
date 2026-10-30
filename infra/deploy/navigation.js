function handler(event) {
  var r = event.request;
  var u = r.uri;
  // Deliberate route allowlist: no blanket error-page or extensionless rewrite.
  var route = /^\/(?:stays(?:\/[a-zA-Z0-9-]+)?|login|signup|profile|trips(?:\/[a-zA-Z0-9-]+(?:\/cancel)?)?|checkout\/[a-zA-Z0-9-]+|host(?:\/(?:today|calendar|earnings|listings(?:\/(?:new|[a-zA-Z0-9-]+\/(?:edit|preview)))?))?|admin)\/?$/;
  if ((r.method === 'GET' || r.method === 'HEAD') && (u === '/' || route.test(u))) {
    r.uri = '/index.html';
  }
  return r;
}
