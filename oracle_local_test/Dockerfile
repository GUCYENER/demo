# v3.38.x: Oracle Free 23ai + init scriptleri image'a GÖMÜLÜ.
# Neden: Windows drvfs bind mount, Docker Desktop'ta
#   "error while creating mount source path '/run/desktop/mnt/host/d/...':
#    mkdir /run/desktop/mnt/host/d: file exists"
# mount bug'ına yol açıyordu (IDE/container çökmesi sonrası VM mount state bozulur,
# D: sürücüsünden TÜM bind mount'lar patlar). Scriptleri COPY ile gömünce hiç host
# bind mount kalmaz; oradata named volume'de (Docker VM ext4). Şema + örnek veri
# yine container ilk açılışında init scriptlerinden kurulur — kayıp yok.
FROM gvenzl/oracle-free:23-slim
COPY 01_create_schema.sql      /container-entrypoint-initdb.d/01_create_schema.sql
COPY 02_insert_sample_data.sql /container-entrypoint-initdb.d/02_insert_sample_data.sql
