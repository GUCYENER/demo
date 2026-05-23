"""
VYRA Frontend Server - Smart Cache Development Server
=====================================================
Statik asset'ler için akıllı cache yönetimi:
- ?v= parametreli dosyalar: 1 saat cache (versiyon değiştiğinde otomatik güncellenir)
- JS/CSS/font dosyaları: 10 dakika cache (tekrar tekrar yüklemeyi önler)
- HTML dosyaları: no-cache (her zaman güncel)

v2.30.1: No-cache → Smart cache (development + performance)
v3.32.0: Port-busy temiz hata (WinError 10048) — TIME_WAIT reuse + clear message.
"""
import http.server
import socketserver
import sys

PORT = 5500


class ReusableTCPServer(socketserver.TCPServer):
    """v3.32.0: SO_REUSEADDR ayarı TIME_WAIT durumundaki socket'i tekrar bind edilebilir kılar.
    Bu, dev döngüde sık sık stop/start yapıldığında WinError 10048'i azaltır."""
    allow_reuse_address = True

# Cache süreleri (saniye)
CACHE_LONG = 3600     # 1 saat — versiyonlu dosyalar (?v=)
CACHE_SHORT = 0       # v3.4.5: Dev modunda no-cache — JS/CSS değişiklikleri anında geçerli
CACHE_NONE = 0        # No-cache — HTML ve diğer


class SmartCacheHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with smart cache headers based on file type."""
    
    def end_headers(self):
        path = self.path.lower()
        
        # Versiyonlu dosyalar (?v=...) — uzun cache (versiyon değişince bust olur)
        if '?v=' in path:
            self.send_header('Cache-Control', f'public, max-age={CACHE_LONG}')
        
        # Statik asset'ler (versiyonsuz)
        elif any(path.endswith(ext) for ext in ('.js', '.css', '.woff2', '.woff', '.ttf', '.png', '.jpg', '.svg', '.ico')):
            if CACHE_SHORT > 0:
                self.send_header('Cache-Control', f'public, max-age={CACHE_SHORT}')
            else:
                # Dev mod: no-cache
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
        
        # HTML ve diğer — no-cache
        else:
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        
        super().end_headers()


if __name__ == "__main__":
    try:
        with ReusableTCPServer(("", PORT), SmartCacheHandler) as httpd:
            print(f"[VYRA Frontend] http://localhost:{PORT}")
            print(f"  Smart cache: HTML=no-cache | JS/CSS={CACHE_SHORT}s | ?v=={CACHE_LONG}s")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nKapatılıyor...")
                sys.exit(0)
    except OSError as e:
        # WinError 10048 / EADDRINUSE — port zaten başka bir process'te
        if getattr(e, "winerror", None) == 10048 or e.errno in (48, 98):
            print(f"[VYRA Frontend] HATA: Port {PORT} zaten kullanımda.")
            print(f"  Çözüm:")
            print(f"    1) .\\stop.ps1  (mevcut servisleri durdur)")
            print(f"    2) Veya Windows: netstat -ano | findstr :{PORT}  -> taskkill /PID <pid> /F")
            print(f"    3) Sonra: .\\start.ps1")
            sys.exit(2)
        # Diğer OS hataları — orijinal traceback'i koru
        raise
