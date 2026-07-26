FROM python:3.12-slim

WORKDIR /app

ARG REQS=requirements-api.txt
COPY ${REQS} requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/digital_twin_builder/ .
