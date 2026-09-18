FROM python:3.11-slim

COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .

ENTRYPOINT ["slam-regression"]
CMD ["--help"]
