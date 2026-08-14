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

# pymupdf 锁死 1.28.0：1.28.2 起 `import fitz` 会把弃用警告打到 stdout，
# 污染 s1parse 的纯 JSON 输出契约。s1parse 就跑在本镜像内，放开上界会直接打死解析链路。
RUN python3 -m pip install --no-cache-dir --break-system-packages "python-docx==1.1.2" "pymupdf==1.28.0"
RUN python3 -m pip install --no-cache-dir --break-system-packages "pandas>=2.2.0" "openpyxl>=3.1.0"
RUN python3 -m pip install --no-cache-dir --break-system-packages "lxml>=5.2.0" "docxcompose>=2.2.0" "PyYAML>=6.0.0"

COPY opencode.json /workspace/opencode.json
COPY .opencode /workspace/.opencode
COPY skills /workspace/skills
COPY docker-entrypoint.sh /usr/local/bin/opencode-entrypoint

RUN chmod +x /usr/local/bin/opencode-entrypoint \
    && mkdir -p /root/.local/share/opencode /workspace/.opencode/skills \
    && cp -R /workspace/skills/. /workspace/.opencode/skills/
# harness-09：命令别名 wrapper 不再在构建期 printf 固化；事实源为
# skills/commands.json，由 docker-entrypoint.sh 的 register_skill_commands
# 在每次容器启动时生成到 /usr/local/bin。新增 skill 别名只需改 commands.json。

EXPOSE 4096

ENTRYPOINT ["opencode-entrypoint"]
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096", "--cors", "http://localhost", "--cors", "http://127.0.0.1"]
