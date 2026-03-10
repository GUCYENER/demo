"""
VYRA Frontend Server - Smart Cache Development Server
=====================================================
Statik asset'ler için akıllı cache yönetimi:
- ?v= parametreli dosyalar: 1 saat cache (versiyon değiştiğinde otomatik güncellenir)
- JS/CSS/font dosyaları: 10 dakika cache (tekrar tekrar yüklemeyi önler)
- HTML dosyaları: no-cache (her zaman güncel)

v2.30.1: No-cache → Smart cache (development + performance)
"""
import http.server
import socketserver
import sys

PORT = 5500

# Cache süreleri (saniye)
CACHE_LONG = 3600     # 1 saat — versiyonlu dosyalar (?v=)
CACHE_SHORT = 600     # 10 dk — statik asset'ler (js/css/font/img)
CACHE_NONE = 0        # No-cache — HTML ve diğer


class SmartCacheHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with smart cache headers based on file type."""
    
    def end_headers(self):
        path = self.path.lower()
        
        # Versiyonlu dosyalar (?v=...) — uzun cache (versiyon değişince bust olur)
        if '?v=' in path:
            self.send_header('Cache-Control', f'public, max-age={CACHE_LONG}')
        
        # Statik asset'ler (versiyonsuz) — kısa cache
        elif any(path.endswith(ext) for ext in ('.js', '.css', '.woff2', '.woff', '.ttf', '.png', '.jpg', '.svg', '.ico')):
            self.send_header('Cache-Control', f'public, max-age={CACHE_SHORT}')
        
        # HTML ve diğer — no-cache
        else:
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), SmartCacheHandler) as httpd:
        print(f"[VYRA Frontend] http://localhost:{PORT}")
        print(f"  Smart cache: HTML=no-cache | JS/CSS={CACHE_SHORT}s | ?v=={CACHE_LONG}s")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nKapatılıyor...")
            sys.exit(0)
