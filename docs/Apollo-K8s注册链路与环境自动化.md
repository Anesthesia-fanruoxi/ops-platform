# Apollo K8s 注册链路与环境自动化记录

更新时间：2026-11-26  
集群：192.168.3.8  
当前环境：goshop-test

## 1. 当前结论

Apollo 配置主体存放在 MySQL，但一个环境要完整可用，至少涉及：

- `ApolloConfigDB`：AppNamespace、Item、Release、Commit、Audit，真正的配置内容。
- `ApolloPortalDB`：App、AppNamespace、ServerConfig、Users，Portal 的应用列表、环境和用户。
- ConfigService 内置 Eureka，AdminService 注册到这个 Eureka。
- Portal 通过 Meta Server（ConfigService）发现 AdminService。

## 2. 注册链路

```text
Apollo Portal
  -> TEST_META=http://apollo-configservice:8080
  -> ConfigService /services/admin
  -> ConfigService 内置 Eureka
  -> AdminService（apollo-adminservice:8090）
```

关键点：

- AdminService 注册地址来自 **ApolloConfigDB.ServerConfig.eureka.service.url**，不是 Deployment 里的 `EUREKA_CLIENT_SERVICE_URL_DEFAULTZONE`。
- 本次故障时该值是 `http://localhost:8080/eureka/`，AdminService 日志实际请求 `localhost:8080`，因此 Portal 一直报：

```text
No available admin server
Env is down. env: TEST
```

修复后的值：

```text
eureka.service.url=http://apollo-configservice:8080/eureka/
```

修复后 AdminService 注册成功，Portal 日志出现：

```text
Env revived because env health check success. env: TEST
```

## 3. 本次已修复内容

### 3.1 Apollo 注册

- 更新 `ApolloConfigDB.ServerConfig.eureka.service.url` 为 ConfigService 的 K8s Service 地址。
- 重启 `apollo-configservice`、`apollo-adminservice`、`apollo-portal`。
- 已将这条 SQL 写进 `mysql-init` 初始化模板，后续新环境自动设置。
- 仓库风格 Deployment 模板已注入 `APOLLO_META=http://apollo-configservice.{project}-{env}-middleware.svc.cluster.local:8080`，覆盖应用 jar 内旧的 Apollo 地址。

### 3.2 Apollo Portal 外网访问

`apollo-portal` 从 ClusterIP 改为 NodePort：

```text
http://192.168.3.8:30070
```

默认账号：`apollo / admin`。

模板中 Portal Service 已改为 NodePort，端口由集群自动分配，避免多环境固定端口冲突。

### 3.3 中间件模板其他实测问题

- MySQL 初始化脚本中的反引号和 JSON 双引号必须转义，否则 shell 会把 `Key`、`Value` 当命令执行，Job 重试后失败。
- Eureka 镜像启动命令不读取 `JAVA_OPTS`，需要 `JAVA_TOOL_OPTIONS` 限制堆内存，否则 1Gi limit 下 OOMKilled。
- XXL-Job 镜像实际使用 `MYSQL-HOST/PORT/DB/USER/PWD`，监听端口为 `9080`；模板原来使用 `DB_*` 和 8080，导致数据库 URL 错误、探针永远不 Ready。
- XXL-Job 镜像需要旧版表字段，已加入兼容字段：`xxl_job_info.job_cron`、`job_desc`、`xxl_job_group.title`。

## 4. 当前 Goshop 环境状态

- 中间件 Pod 全部 `1/1 Running`：MySQL、Redis、RabbitMQ、Zookeeper、Elasticsearch、Apollo、Eureka、Seata、XXL-Job。
- 业务镜像：19 仓、44 个服务已构建并推送 `hub.hzbxhd.com/goshop-test:<tag>`。
- 业务 Service：41 个 ClusterIP Service 已创建。
- `java-option` ConfigMap 已创建，当前通用值：

```text
jdk8-agent=-Xms512m -Xmx1024m -XX:+UseG1GC -Dfile.encoding=UTF-8 -Duser.timezone=Asia/Shanghai
```

- `asset-distribution-platform` 已做过一次启动测试：镜像可拉取、容器可启动，但因 Apollo 中没有应用配置，启动报 `缺少必需的配置: spring.datasource.url`。

## 5. 6.43 旧环境 Apollo 数据情况

192.168.6.43 MySQL 中已有：

- `ApolloConfigDB`：约 74 个应用、129 个 namespace、19023 条 Item、392 个 Release。
- `ApolloPortalDB`：约 73 个应用、111 个 namespace、1 个用户。
- Portal 环境当前为 `dev`，Meta 地址为 `http://192.168.6.43:8082`。

迁移时不能只复制一个库：

1. 两个 Apollo 库都要迁移。
2. `ApolloPortalDB.ServerConfig` 要改成：

```text
apollo.portal.envs=test
apollo.portal.meta.servers={"TEST":"http://apollo-configservice:8080"}
```

3. Apollo Item 中写死的旧地址要批量替换：
   - MySQL、Redis、RabbitMQ、Eureka、Apollo。
4. 6.43 上的业务库（如 `asset_distribution_platform_test`、`bill_config_test`、`shop_test`）不属于 Apollo，需要单独迁移，或者让配置继续指向旧库。

## 6. 一键扩展环境需要自动化的步骤

当前手工步骤：

1. 创建项目/环境。
2. 创建两个 namespace。
3. 生成并 apply 中间件 YAML。
4. 初始化 MySQL 库表。
5. 修复 Apollo Eureka 地址和 Portal Meta。
6. 创建 `java-option`、`harbor` 等命名空间资源。
7. 编译 19 个仓库、44 个服务。
8. 构建并推送 44 个镜像。
9. apply 业务 Deployment 和 Service。
10. 等待 Pod/探针就绪，失败时看日志和回滚。

后续在 ops 平台中建议做成幂等状态机：

```text
预检查
  -> namespace
  -> middleware
  -> DB init
  -> Apollo env/config
  -> java-option/secrets
  -> build & push
  -> apply services
  -> apply deployments
  -> readiness gate
  -> notify
```

每个步骤要记录：

- 执行时间、耗时、成功/失败。
- 实际执行的命令和产物路径。
- 失败原因和重试次数。
- 可重入标记，避免重复 apply 破坏已有数据。

## 7. 待办

- [ ] 从 6.43 逻辑导出 ApolloConfigDB、ApolloPortalDB。
- [ ] 导入新 K8s MySQL，并改写 Portal 环境/Meta。
- [ ] 批量修正 Apollo Item 中的旧中间件地址。
- [ ] 迁移业务库（至少 `asset_distribution_platform_test`）。
- [x] 给业务 Deployment 注入 `APOLLO_META`（模板已修）。
- [ ] 修 `asset-distribution-platform` 的 `server.port` 与探针端口是否一致。
- [ ] 将上述步骤收敛为 ops 的一键扩展环境任务（进行中）。
- [ ] 流水线构建成功后自动更新 YAML tag、apply Deployment、等待 readiness。
- [ ] 引入 Higress 统一入口，替代每环境手工 Nginx/端口。

## 8. 2026-11-26 部署侧连通性验证

从 `goshop-test-service` 的临时 busybox Pod 验证到中间件 namespace 的 FQDN/端口：

```text
mysql.goshop-test-middleware:3306            OK
redis.goshop-test-middleware:6379            OK
rabbitmq.goshop-test-middleware:5672         OK
zookeeper.goshop-test-middleware:2181        OK
elasticsearch.goshop-test-middleware:9200    OK
apollo-configservice.goshop-test-middleware:8080  OK
apollo-adminservice.goshop-test-middleware:8090   OK
apollo-portal.goshop-test-middleware:8070         OK
eureka.goshop-test-middleware:8761           OK
seata-server.goshop-test-middleware:8091     OK
xxljob.goshop-test-middleware:8080           OK
```

说明：

- busybox 镜像没有 `getent`，所以当时用 `getent hosts` 检查 DNS 显示失败；实际 `nc` 已通过 FQDN 建立 TCP，DNS 正常。
- 当前所有中间件 Pod 均为 `1/1 Running`。
- 业务侧连接 Web 控制台的 Portal NodePort：`http://192.168.3.8:30070`。
- `asset-distribution-platform` 测试 Pod 能拉镜像并启动容器；应用因 Apollo 配置未导入而退出，属于业务配置问题，不是部署/网络问题。
- 当前业务 namespace 仍只有测试 Deployment；其余 40 个 Deployment 未 apply。
- 2026-11-26 已把 41 个仓库风格 Deployment YAML 重新生成到远程目录，全部注入 `APOLLO_META`（未 apply）。
