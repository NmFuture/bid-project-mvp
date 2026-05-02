FROM node:22-bookworm

ARG OPENCODE_NPM_VERSION=1.14.18

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORMAT_CLEANER_ALLOW_SYSTEM_PY=1 \
    OPENCODE_HOME=/root/.local/share/opencode

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "opencode-ai@${OPENCODE_NPM_VERSION}" \
    && python3 -m pip install --no-cache-dir --break-system-packages \
      "python-docx==1.1.2" \
      "pymupdf>=1.24.0" \
      "pandas>=2.2.0" \
      "openpyxl>=3.1.0" \
      "lxml>=5.2.0" \
      "docxcompose>=1.4.0" \
      "PyYAML>=6.0.0" \
    && npm cache clean --force

COPY opencode.json /workspace/opencode.json
COPY .opencode /workspace/.opencode
COPY skill /workspace/skill
COPY docker-entrypoint.sh /usr/local/bin/opencode-entrypoint

RUN chmod +x /usr/local/bin/opencode-entrypoint \
    && mkdir -p /root/.local/share/opencode /workspace/.opencode/skills \
    && cp -R /workspace/skill/. /workspace/.opencode/skills/ \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s1parse <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tender-structured-parser/scripts/run_from_manifest.py "$1"' \
      > /usr/local/bin/s1parse \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s7assemble <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-assembler/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s7assemble \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s4gap <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-gap-planner/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s4gap \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s4fill <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-table-filler/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s4fill \
    && chmod +x /usr/local/bin/s1parse /usr/local/bin/s7assemble /usr/local/bin/s4gap /usr/local/bin/s4fill

EXPOSE 4096

ENTRYPOINT ["opencode-entrypoint"]
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096", "--cors", "http://localhost", "--cors", "http://127.0.0.1"]
