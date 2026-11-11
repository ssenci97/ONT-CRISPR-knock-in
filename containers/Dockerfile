ARG BASE
FROM ${BASE}

LABEL org.opencontainers.image.title="ont-knockin-val"
LABEL org.opencontainers.image.description="KNOCKIN-VAL base plus CRISPRLungo and CRISPResso2. Academic non-commercial use. NOT REDISTRIBUTABLE: see /opt/licenses/README.md."

ARG LUNGO_REPO=https://github.com/pinellolab/CRISPRLungo
ARG LUNGO_COMMIT=e31ea36a3373c018cdee7b61ede8f571e4ecbf7f

RUN conda install -q -n kv -c conda-forge -c bioconda crispresso2 \
    && conda list -n kv crispresso2 --json > /opt/crispresso2.version.json \
    && conda clean -afy

RUN git clone -q "$LUNGO_REPO" "$TOOLS/CRISPRLungo" \
    && git -C "$TOOLS/CRISPRLungo" checkout -q -f "$LUNGO_COMMIT" \
    && conda run -n kv pip install -q --no-deps --no-build-isolation -e "$TOOLS/CRISPRLungo" \
    && [ "$(git -C "$TOOLS/CRISPRLungo" rev-parse HEAD)" = "$LUNGO_COMMIT" ]

RUN conda run -n kv CRISPResso --version && conda run -n kv CRISPRlungo --help > /dev/null
