"""Delft3D-FM Viewer Server Entrypoint with automatic port conflict resolution.
"""
import socket
import uvicorn
import webbrowser
import sys
from pathlib import Path

def find_available_port(start_port: int = 8088, max_attempts: int = 50) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"無法在 {start_port} 至 {start_port + max_attempts} 範圍內找到可用連接埠。")

def main():
    port = find_available_port(8088)
    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print(f"🚀 Delft3D-FM 多分區水理時空展示圖台已啟動！")
    print(f"👉 圖台網址: {url}")
    print("=" * 60)

    # 嘗試自動在預設瀏覽器開啟
    try:
        webbrowser.open(url)
    except Exception:
        pass

    src_path = Path(__file__).resolve().parent.parent
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    from dfm_viewer.api import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    main()
