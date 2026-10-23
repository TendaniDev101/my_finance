# Verified: numpy/pandas/scipy at the pinned versions all publish cp314
# manylinux wheels, so no compiler toolchain is needed in the image - plain
# pip install is enough and keeps the build fast and the image small.
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run injects PORT at runtime (default 8080) and requires the
# container to listen on it, bound to 0.0.0.0 (not 127.0.0.1). Shell form
# (not exec/JSON form) is required here so ${PORT} actually gets expanded.
ENV PORT=8080
EXPOSE 8080
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
