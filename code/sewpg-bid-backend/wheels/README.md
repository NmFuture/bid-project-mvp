# 预置 wheel 目录

本目录通常为空，构建时 `pip` 照常从网络安装。

当某个体积大的依赖在目标环境反复下载失败时（`pip` 不支持断点续传，中断即整包作废），
可在目标主机上用 `wget -c` 断点续传取回，校验哈希后放入本目录，`pip --find-links`
会优先使用本地文件。

```bash
wget -c --tries=50 --timeout=60 --waitretry=5 -O <name>.whl <url>
sha256sum <name>.whl    # 必须与 pip 报告的 Expected sha256 一致
```

`*.whl` 已在 `.gitignore` 中排除，不会被提交。
