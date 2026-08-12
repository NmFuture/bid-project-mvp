"""命令行入口：单独给一份 docx 加图表题注。

    python -m app.document_processing.technical_document.captioning <manifest.json>
"""

from .runner import main


raise SystemExit(main())
