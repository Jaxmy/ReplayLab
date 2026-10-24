# Third-party components

- **NautilusTrader 1.231.0**: LGPL-3.0, installed unmodified from PyPI in `.venv`. Source: https://github.com/nautechsystems/nautilus_trader . Included package contains Python/Cython sources and native components. Its license governs that dependency; the app's MIT license does not replace it.
- **Lightweight Charts 5.2.1**: Apache-2.0, TradingView Inc. Source: https://github.com/tradingview/lightweight-charts . Bundled unmodified browser build in `web/` and `vscode/media/`; license copied alongside the build. TradingView attribution is retained in the UI.
- **Backtest Manager**: MIT, copyright 2025 Backtest Manager. Studied as a design reference during development; it is not bundled as a runtime component and no endorsement is implied.
- Other Python/npm packages remain governed by their included licenses. Versions are recorded in `requirements-lock.txt` and `package-lock.json`.

- AKShare Sina historical decoder: MIT, Copyright (c) 2019-2026 Albert King. Source: https://github.com/akfamily/akshare . Extracted hk_js_decode is bundled in vendor/akshare-decoder/decode.cjs with original LICENSE; used only to decode public index history, without executing remote response code.
