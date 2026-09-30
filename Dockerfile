# The application image: FastAPI backend and Streamlit front end.
#
# The engine is a DEPENDENCY, not part of this repository, so it has to come
# from somewhere at build time. Two ways, and neither reaches the internet at
# run time, which is what matters in a bank container with no egress:
#
#   1. Vendored wheels (the deployment path). Put the ifrs9qdb wheel and its
#      dependencies -- including the excel extra (openpyxl, lxml), which the
#      pipeline needs to read the extracts -- in ./wheels/ and build with the
#      default ENGINE_SPEC.
#
#        pip wheel -w wheels "../ifrs9qdb_py[excel]"
#        docker build -t ifrs9-app .
#
#   2. An index that carries it, for development:
#
#        docker build --build-arg ENGINE_SPEC="ifrs9qdb[excel]>=0.26" \
#                     --build-arg PIP_ARGS="" -t ifrs9-app .
FROM python:3.12-slim

ARG ENGINE_SPEC=ifrs9qdb[excel]
ARG PIP_ARGS=--no-index

RUN useradd --create-home --uid 10001 ifrs9

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    IFRS9_PROJECT_ROOT=/data/project \
    IFRS9_RUNS_DIR=/data/runs \
    IFRS9_BACKEND=http://127.0.0.1:8000

# An empty wheels/ is fine; .keep makes the COPY succeed either way.
COPY wheels/ /wheels/
RUN pip install --no-cache-dir ${PIP_ARGS} --find-links=/wheels "${ENGINE_SPEC}"

COPY pyproject.toml README.md ./
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY app.py config.yml ./
COPY config/ ./config/
COPY data-raw/ ./data-raw/
COPY .streamlit/ ./.streamlit/
RUN pip install --no-cache-dir --no-deps . \
 && pip install --no-cache-dir "fastapi>=0.110" "uvicorn[standard]>=0.27" \
      "pydantic>=2.5" "python-multipart>=0.0.9" "streamlit>=1.64" \
      "plotly>=5.20" "requests>=2.31"

# Runs, inputs and the PROJECT (config.yml, config/, data-raw/static/, config
# versions, the audit log) are DATA, not image content: mount them, so the
# image is identical across environments and a redeploy cannot lose a run or
# a config edit. The first start seeds /data/project from the image's copies.
RUN mkdir -p /data/runs /data/input /data/output /data/project \
 && chown -R ifrs9:ifrs9 /data
VOLUME ["/data"]

USER ifrs9

# One service per container. compose starts this image twice, once as the API
# and once as the interface; SERVICE picks which.
EXPOSE 8000 8501
ENV SERVICE=api
CMD ["sh", "-c", "if [ \"$SERVICE\" = ui ]; then \
       exec streamlit run app.py --server.port 8501 --server.address 0.0.0.0; \
     else \
       exec uvicorn backend.main:app --host 0.0.0.0 --port 8000; \
     fi"]
