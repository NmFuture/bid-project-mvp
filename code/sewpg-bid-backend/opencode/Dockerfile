FROM node:22-bookworm

ARG OPENCODE_NPM_VERSION=1.18.2
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORMAT_CLEANER_ALLOW_SYSTEM_PY=1 \
    OPENCODE_HOME=/root/.local/share/opencode \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "opencode-ai@${OPENCODE_NPM_VERSION}" \
    && npm cache clean --force

RUN python3 -m pip install --no-cache-dir --break-system-packages "python-docx==1.1.2" "pymupdf>=1.24.0"
RUN python3 -m pip install --no-cache-dir --break-system-packages "pandas>=2.2.0" "openpyxl>=3.1.0"
RUN python3 -m pip install --no-cache-dir --break-system-packages "lxml>=5.2.0" "docxcompose>=2.2.0" "PyYAML>=6.0.0"

COPY opencode.json /workspace/opencode.json
COPY .opencode /workspace/.opencode
COPY skills /workspace/skills
COPY docker-entrypoint.sh /usr/local/bin/opencode-entrypoint

RUN chmod +x /usr/local/bin/opencode-entrypoint \
    && mkdir -p /root/.local/share/opencode /workspace/.opencode/skills \
    && cp -R /workspace/skills/. /workspace/.opencode/skills/ \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -lt 1 ]; then' \
      '  echo "usage: s1parse [prepare|overview|search|read|table|window|submit|status|validate|finalize] <manifest> [...]" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/s1parse_router.py "$@"' \
      > /usr/local/bin/s1parse \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s2toc <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-outline-generator/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s2toc \
    && printf '%s\n' \
      '#!/bin/sh' \
      'case "$1" in' \
      '  prepare|template|template-headings|headings|search|section|next-batch|read|window|table|tables|review-batch|decision-next|decision-batch|decision-reopen|review-corrections|appendix-next|appendix-decision-batch|review-complete|decisions|compose|validate|status|finalize) ;;' \
      '  *) echo "usage: s2outline [prepare|template|template-headings|headings|search|section|next-batch|read|window|table|tables|review-batch|decision-next|decision-batch|decision-reopen|review-corrections|appendix-next|appendix-decision-batch|review-complete|decisions|compose|validate|status|finalize] <manifest> [...]" >&2; exit 64 ;;' \
      'esac' \
      'exec python3 /workspace/.opencode/skills/bid-tech-outline-generator/scripts/run_from_manifest.py --require-compose "$@"' \
      > /usr/local/bin/s2outline \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: business-outline <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-business-outline-generator/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/business-outline \
    && printf '%s\n' \
      '#!/bin/sh' \
      'case "$1" in' \
      '  prepare|overview|search|read|window|submit|validate|status|finalize) ;;' \
      '  *) echo "usage: btplnav [prepare|overview|search|read|window|submit|validate|status|finalize] <manifest> [...]" >&2; exit 64 ;;' \
      'esac' \
      'exec python3 /workspace/.opencode/skills/bid-business-template-extractor/scripts/run_from_manifest.py "$@"' \
      > /usr/local/bin/btplnav \
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
      '  echo "usage: businessassemble <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-business-assembler/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/businessassemble \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: businessformat <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-business-format-cleaner/scripts/run_from_manifest.py "$1" --response summary' \
      > /usr/local/bin/businessformat \
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
      '  echo "usage: businessgap <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-business-gap-planner/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/businessgap \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: businesstablefill <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-business-table-fill/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/businesstablefill \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s4fill <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-table-filler/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s4fill \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: s4wordfill <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/bid-tech-word-placeholder-filler/scripts/run_from_manifest.py --manifest "$1" --response summary' \
      > /usr/local/bin/s4wordfill \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ "$#" -ne 1 ]; then' \
      '  echo "usage: wikibuild <manifest>" >&2' \
      '  exit 64' \
      'fi' \
      'exec python3 /workspace/.opencode/skills/wikibuild_router.py "$1"' \
      > /usr/local/bin/wikibuild \
    && chmod +x /usr/local/bin/s1parse /usr/local/bin/s2toc /usr/local/bin/s2outline /usr/local/bin/business-outline /usr/local/bin/btplnav /usr/local/bin/s7assemble /usr/local/bin/businessassemble /usr/local/bin/businessformat /usr/local/bin/s4gap /usr/local/bin/businessgap /usr/local/bin/businesstablefill /usr/local/bin/s4fill /usr/local/bin/s4wordfill /usr/local/bin/wikibuild

EXPOSE 4096

ENTRYPOINT ["opencode-entrypoint"]
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096", "--cors", "http://localhost", "--cors", "http://127.0.0.1"]
