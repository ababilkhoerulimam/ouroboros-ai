FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/app \
    MPLCONFIGDIR=/tmp/matplotlib \
    IPYTHONDIR=/tmp/ipython \
    JUPYTER_RUNTIME_DIR=/tmp/jupyter-runtime

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
# Prompt adalah data runtime, bukan bagian paket: `pip install .` menaruh modul
# di site-packages, sementara `phases._default_prompts_dir()` jatuh ke
# `cwd/prompts`. Tanpa baris ini container gagal di F1 dengan
# "prompt tidak ditemukan: /usr/local/lib/python3.11/prompts/system.md".
COPY prompts ./prompts

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 swarmfold \
    && mkdir -p /runs /inbox /tmp/matplotlib /tmp/ipython /tmp/jupyter-runtime \
    # Cache font dibangun di sini, bukan di kernel: font_manager memanggil
    # `fc-list` lewat subprocess saat cache belum ada, dan kernel analisis
    # memblokir subprocess (kernel.py) sehingga `import matplotlib.pyplot`
    # gagal RuntimeError pada cell pertama di container baru.
    && python -c "import matplotlib.font_manager as fm; fm.fontManager" \
    && chown -R swarmfold:swarmfold /app /runs /tmp/matplotlib /tmp/ipython /tmp/jupyter-runtime

USER swarmfold

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "swarmfold.api:app", "--host", "0.0.0.0", "--port", "8080"]
