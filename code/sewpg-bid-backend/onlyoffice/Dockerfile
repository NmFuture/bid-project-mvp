ARG ONLYOFFICE_BASE_IMAGE=onlyoffice/documentserver:9.3.1.2@sha256:0d263ef0bc0cd11d036586fd0aafe7de41a3cdb281dd582c012b142cd961fc31
ARG ONLYOFFICE_FONT_BUILDER_IMAGE=debian:bookworm-slim@sha256:63a496b5d3b99214b39f5ed70eb71a61e590a77979c79cbee4faf991f8c0783e

FROM ${ONLYOFFICE_FONT_BUILDER_IMAGE} AS font-builder

ARG NOTO_CJK_PACKAGE_VERSION=1:20220127+repack1-1
ARG LIBERATION_PACKAGE_VERSION=2.1.5-1
ARG FONTTOOLS_PACKAGE_VERSION=4.38.0-1+deb12u1

COPY extract-noto-sc.py /usr/local/bin/extract-noto-sc.py

RUN apt-get update \
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
