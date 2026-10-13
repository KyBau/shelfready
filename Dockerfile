FROM python:3.12-slim
WORKDIR /app
COPY server.py ./
ENV HOST=0.0.0.0 PORT=8080 SHELFREADY_STORE=allbirds.com SHELFREADY_ALLOW_ANY_STORE=1
EXPOSE 8080
USER nobody
CMD ["python", "server.py", "--http"]
