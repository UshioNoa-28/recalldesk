# Java 后端镜像：构建期用 Maven 打可执行 jar，运行期只带 JRE。
# 只接线，不含业务逻辑——业务在 backend/ 的四个模块里。

FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src

# 先只拷 pom，把依赖层单独缓存：改代码不必重下依赖
COPY backend/pom.xml .
COPY backend/domain/pom.xml domain/pom.xml
COPY backend/application/pom.xml application/pom.xml
COPY backend/infrastructure/pom.xml infrastructure/pom.xml
COPY backend/interfaces/pom.xml interfaces/pom.xml
RUN mvn -B -q -pl interfaces -am dependency:go-offline || true

COPY backend/domain domain
COPY backend/application application
COPY backend/infrastructure infrastructure
COPY backend/interfaces interfaces
RUN mvn -B -q -pl interfaces -am package -DskipTests

FROM eclipse-temurin:21-jre
# compose 的 api healthcheck 用 curl；JRE 镜像不保证带它，缺了健康检查永远失败，
# 依赖 api 健康的 frontend 就一直不启动
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# 唯一可执行产物：interfaces 的 boot jar（其余模块编译期产物都在它里面）
COPY --from=build /src/interfaces/target/recalldesk-interfaces-*.jar /app/app.jar

# worker 角色由命令行的 --recalldesk.worker.role 决定；不传就是 web 服务
EXPOSE 8090
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
