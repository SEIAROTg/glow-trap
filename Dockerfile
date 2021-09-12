FROM python:3-alpine

WORKDIR /app
COPY . .
RUN apk update
RUN apk add --no-cache --virtual .build-deps build-base openssl
RUN pip3 install --no-cache-dir -r requirements.txt
RUN ./certgen.sh
RUN apk del --no-cache .build-deps
RUN apk add --no-cache dhcp chrony
RUN touch /var/lib/dhcp/dhcpd.leases

ENTRYPOINT ["./entrypoint.sh"]
