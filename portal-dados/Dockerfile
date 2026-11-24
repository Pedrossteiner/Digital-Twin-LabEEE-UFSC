# Etapa 1: transforma o modelo IFC numa versão leve para o navegador (leva ~1 min).
# Se falhar, o build continua e a página lê o IFC direto (mais lento).
FROM node:20-slim AS modelo
WORKDIR /c
RUN npm install --no-audit --no-fund web-ifc@0.0.57
COPY app/static/cozinhar.mjs cozinhar_modelo.mjs ./
COPY modelo/ ./modelo/
RUN mkdir -p saida && (node cozinhar_modelo.mjs modelo/Labeee_gemeo.ifc saida/Labeee_gemeo.bin.gz \
    || echo "AVISO: não consegui cozinhar o modelo; a página vai ler o IFC direto")

# Etapa 2: o portal
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY baixar_vendor.py /tmp/
RUN python /tmp/baixar_vendor.py /app/static/vendor
COPY app/ .
COPY modelo/ /app/modelo/
COPY --from=modelo /c/saida/ /app/modelo/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd -m -u 1000 portal && mkdir -p /dados_mensais && chown portal /dados_mensais
USER portal
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude')"
ENTRYPOINT ["/entrypoint.sh"]
