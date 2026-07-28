# 本地预置 wheel 目录
#
# 用途：5090 等网络受限环境下，超大 wheel（如 nvidia-cublas，423 MB）经代理下载
# 容易中途截断导致 pip 哈希校验失败。可先在宿主机用 wget -c 断点续传下好，放入本目录，
# 构建时 pip --find-links 会优先使用本地文件。
#
# 约定：*.whl 不进版本控制（见 .gitignore），本目录在仓库中保持为空。
