FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user app ./app
RUN mkdir -p /app/downloads && chown -R user:user /app

USER user
ENV PORT=7860
EXPOSE 7860

CMD ["python", "-m", "app"]
