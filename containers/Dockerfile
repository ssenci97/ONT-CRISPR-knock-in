ARG BASE_REF=docker.io/condaforge/miniforge3@sha256:569afc65b5338d35e276adf9a860025cd37a677659d19dcb71fc1d4c2063a94e
FROM ${BASE_REF}

LABEL org.opencontainers.image.title="ont-knockin-val"
LABEL org.opencontainers.image.description="ALPINE and CRISPRLungo on ONT CRISPR knock-in amplicons. Academic non-commercial use."
LABEL org.opencontainers.image.licenses="MIT AND AGPL-3.0-only"
LABEL org.opencontainers.image.source="https://github.com/ssenci97/ONT-CRISPR-knock-in"

ARG ALPINE_REPO=https://github.com/Maggi-Chen/ALPINE
ARG ALPINE_COMMIT=b59121d132f20e5056b76038b50dc136a91a756b
ARG LUNGO_REPO=https://github.com/pinellolab/CRISPRLungo
ARG LUNGO_COMMIT=e31ea36a3373c018cdee7b61ede8f571e4ecbf7f

ENV TOOLS=/opt/tools CONDA_ALWAYS_YES=true MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen \
    HOME=/tmp MPLCONFIGDIR=/tmp/mpl PYTHONNOUSERSITE=1

COPY envs/kv.yml containers/kv.lock.tx[t] /tmp/
RUN if [ -s /tmp/kv.lock.txt ]; then conda create -q -n kv --file /tmp/kv.lock.txt; \
    else conda env create -q -f /tmp/kv.yml; fi \
    && grep -E '^[[:space:]]*-[[:space:]]+[a-z0-9_.-]+=' /tmp/kv.yml | sed 's/^[[:space:]]*-[[:space:]]*//' > /opt/conda/envs/kv/conda-meta/pinned \
    && conda clean -afy

RUN conda create -q -p "$TOOLS/minimap2_216" -c conda-forge -c bioconda minimap2=2.16 \
    && conda clean -afy

RUN git config --system --add safe.directory '*' \
    && git clone -q "$ALPINE_REPO" "$TOOLS/ALPINE" \
    && git -C "$TOOLS/ALPINE" checkout -q -f "$ALPINE_COMMIT" \
    && [ "$(git -C "$TOOLS/ALPINE" rev-parse HEAD)" = "$ALPINE_COMMIT" ]

RUN git clone -q "$LUNGO_REPO" "$TOOLS/CRISPRLungo" \
    && git -C "$TOOLS/CRISPRLungo" checkout -q -f "$LUNGO_COMMIT" \
    && [ "$(git -C "$TOOLS/CRISPRLungo" rev-parse HEAD)" = "$LUNGO_COMMIT" ] \
    && conda run -n kv pip install -q --no-deps --no-build-isolation -e "$TOOLS/CRISPRLungo"

COPY LICENSES /opt/licenses
COPY LICENSES.md /opt/licenses/README.md

SHELL ["/bin/bash", "-c"]
RUN export PATH=/opt/conda/envs/kv/bin:$PATH \
    && python -c "import pysam, Bio, yaml, openpyxl, tqdm" \
    && cwltool --version \
    && seqkit version \
    && for b in curl unzip flock git; do command -v "$b" || { echo "MISSING $b"; exit 1; }; done \
    && t="$(type -P time)" && [ -x "$t" ] && "$t" --version | head -1 \
    && CRISPRlungo --help > /dev/null \
    && "$TOOLS/minimap2_216/bin/minimap2" --version
