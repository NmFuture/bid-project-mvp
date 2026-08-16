ARG ONLYOFFICE_BASE_IMAGE=onlyoffice/documentserver:9.3.1.2@sha256:0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31
ARG ONLYOFFICE_FONT_BUILDER_IMAGE=debian:bookworm-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e

FROM ${ONLYOFFICE_FONT_BUILDER_IMAGE} AS font-builder

ARG NOTO_CJK_PACKAGE_VERSION=1:20220127+repack1-1
ARG LIBERATION_PACKAGE_VERSION=2.1.5-1
ARG FONTTOOLS_PACKAGE_VERSION=4.38.0-1+deb12u1
# apt 源锁定到 Debian 官方快照归档：实时源在点发布切换窗口或安全更新后会下架旧版本，
# 曾导致冷构建报 version not found（2026-07 的 12.15 切换）。快照日期与基础镜像同批，
# 对应 bookworm 12.15 归档，见镜像内 /etc/apt/sources.list.d/debian.sources 的注释。
# 升级字体包版本时必须同步更新该快照日期。
ARG DEBIAN_SNAPSHOT=20260713T000000Z

COPY extract-noto-sc.py /usr/local/bin/extract-noto-sc.py

# 快照归档的 Release 文件 Valid-Until 早已过期，签名校验仍由 Signed-By 承担，不受影响。
RUN sed -i \
        -e "s|deb.debian.org/debian-security|snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        -e "s|deb.debian.org/debian|snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99debian-snapshot.conf \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-liberation2="${LIBERATION_PACKAGE_VERSION}" \
        fonts-noto-cjk="${NOTO_CJK_PACKAGE_VERSION}" \
        python3-fonttools="${FONTTOOLS_PACKAGE_VERSION}" \
    && mkdir -p /fontpack/fonts /fontpack/licenses \
    && python3 /usr/local/bin/extract-noto-sc.py \
        /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
        "Noto Sans CJK SC" /fontpack/fonts/NotoSansCJKSC-Regular.otf \
    && python3 /usr/local/bin/extract-noto-sc.py \
        /usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc \
        "Noto Sans CJK SC" /fontpack/fonts/NotoSansCJKSC-Bold.otf \
    && python3 /usr/local/bin/extract-noto-sc.py \
        /usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc \
        "Noto Serif CJK SC" /fontpack/fonts/NotoSerifCJKSC-Regular.otf \
    && python3 /usr/local/bin/extract-noto-sc.py \
        /usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc \
        "Noto Serif CJK SC" /fontpack/fonts/NotoSerifCJKSC-Bold.otf \
    && cp \
        /usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf \
        /usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf \
        /usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf \
        /usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf \
        /fontpack/fonts/ \
    && cp /usr/share/doc/fonts-noto-cjk/copyright /fontpack/licenses/fonts-noto-cjk.copyright \
    && cp /usr/share/doc/fonts-liberation2/copyright /fontpack/licenses/fonts-liberation2.copyright

FROM ${ONLYOFFICE_BASE_IMAGE}

ARG SEWPG_BUILD_REVISION=dev

LABEL org.opencontainers.image.title="SEWPG OnlyOffice Font Pack" \
      org.opencontainers.image.description="OnlyOffice Document Server with the project open-source font contract" \
      org.opencontainers.image.version="9.3.1.2-fontpack-v1" \
      org.opencontainers.image.revision="${SEWPG_BUILD_REVISION}"

COPY --from=font-builder /fontpack/fonts/ /usr/share/fonts/truetype/sewpg/
COPY --from=font-builder /fontpack/licenses/ /usr/share/doc/sewpg-fontpack/
COPY fontconfig/99-sewpg-cjk-font-aliases.conf /etc/fonts/conf.d/99-sewpg-font-aliases.conf
COPY font-contract.json /usr/local/share/sewpg/font-contract.json
COPY verify-fonts.sh /usr/local/bin/sewpg-verify-fonts
COPY docker-entrypoint.sh /usr/local/bin/sewpg-onlyoffice-entrypoint

RUN chmod 0755 \
        /usr/local/bin/sewpg-onlyoffice-entrypoint \
        /usr/local/bin/sewpg-verify-fonts \
    && fc-cache -f
