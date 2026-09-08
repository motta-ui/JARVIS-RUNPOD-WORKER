# V6 reuses the already-built V5 WanGP dependency image.
FROM motta010203/jarvis-worker:v5

COPY jarvis_worker /app/jarvis_worker
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

EXPOSE 7872 22
CMD ["/app/run.sh"]
