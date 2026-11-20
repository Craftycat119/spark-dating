"""Запуск: python run.py  →  http://localhost:8000"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # uvicorn пишет «running on http://0.0.0.0:8000», но в браузере этот адрес не открывается
    print(f"\n  Откройте в браузере:  http://localhost:{port}\n  Админ-панель:         http://localhost:{port}/admin\n", flush=True)
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        reload=os.environ.get("RELOAD", "0") == "1",
        proxy_headers=True,
    )
