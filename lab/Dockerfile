# The Lab Environment: pinned, CPU only. Built once; each Course pins the resulting image id.
FROM python:3.12.10-slim
RUN pip install --no-cache-dir ipykernel==6.29.5 numpy==2.2.6 pandas==2.2.3 matplotlib==3.10.3 scipy==1.15.3 \
    sympy==1.14.0 scikit-learn==1.6.1
# MLOps courses: MLflow tracks to a local folder (the kernel has no network); FastAPI apps are tried with its TestClient.
RUN pip install --no-cache-dir mlflow==2.21.3 fastapi==0.115.12 httpx==0.28.1
ENV MPLBACKEND=module://matplotlib_inline.backend_inline MPLCONFIGDIR=/tmp/mpl HOME=/tmp
WORKDIR /work
