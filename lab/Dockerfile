# The Lab Environment: pinned, CPU only. Built once; each Course pins the resulting image id.
FROM python:3.12.10-slim
RUN pip install --no-cache-dir ipykernel==6.29.5 numpy==2.2.6 pandas==2.2.3 matplotlib==3.10.3 scipy==1.15.3 \
    sympy==1.14.0 scikit-learn==1.6.1
ENV MPLBACKEND=module://matplotlib_inline.backend_inline MPLCONFIGDIR=/tmp/mpl HOME=/tmp
WORKDIR /work
