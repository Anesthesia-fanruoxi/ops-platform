package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
)

// ─── 配置 ────────────────────────────────────────────────────────

type Config struct {
	MasterURL     string // Master 地址
	CommSecret    string // 通信密钥
	Name          string // 节点名称
	AdvertiseAddr string // Master 回推地址（可达 IP/主机名）
	HeartbeatSec  int    // 心跳间隔（秒）
	MaxConcurrent int    // 最大并发构建数
	WorkDir       string // 工作目录
	LogPort       int    // 日志/任务 HTTP 服务端口
}

var cfg Config

// maskSecret 脱敏显示密钥类参数：保留前4后4，中间打码（空/过短全打码）
func maskSecret(s string) string {
	if s == "" {
		return ""
	}
	if len(s) <= 8 {
		return "****"
	}
	return s[:4] + "****" + s[len(s)-4:]
}

// printRuntimeInfo 启动时打印运行环境详情：Docker 版本/数据目录、NFS 挂载、Harbor 登录状态、工作目录等
func printRuntimeInfo() {
	log.Printf("========== 运行环境检查 ==========")

	// Docker：版本 + 数据目录
	dockerVer := runOutput("docker", "--version")
	if dockerVer == "" {
		log.Printf("[Env] Docker: 未安装或不可用")
	} else {
		root := runOutput("docker", "info", "--format", "{{.DockerRootDir}}")
		log.Printf("[Env] Docker: %s | 数据目录: %s", dockerVer, root)
		// Harbor / 镜像仓库登录状态（读取 docker config.json 的 auths，仅地址不含凭据）
		regs := dockerRegistries()
		if len(regs) > 0 {
			log.Printf("[Env] Harbor/Registry 已登录: %s", strings.Join(regs, ", "))
		} else {
			log.Printf("[Env] Harbor/Registry: 未登录任何镜像仓库")
		}
	}

	// NFS 挂载（挂载源 → 挂载点，含前端 web 目录）
	nfs := runOutput("sh", "-c", "mount | grep -iE ' nfs | nfs4 ' || true")
	if nfs == "" {
		log.Printf("[Env] NFS: 未检测到挂载")
	} else {
		log.Printf("[Env] NFS 挂载:")
		for _, line := range strings.Split(nfs, "\n") {
			if strings.TrimSpace(line) != "" {
				log.Printf("    %s", line)
			}
		}
	}

	// 工作目录 / 构建保留
	log.Printf("[Env] 工作目录: %s", cfg.WorkDir)
	log.Printf("[Env] 构建保留数: 随任务下发（默认 5）")
	log.Printf("==================================")
}

// runOutput 执行命令并返回 stdout（去首尾空白）；失败返回空串
func runOutput(name string, args ...string) string {
	cmd := exec.Command(name, args...)
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// dockerRegistries 读取 ~/.docker/config.json 中已登录的镜像仓库地址（脱敏：仅地址，不含凭据）
func dockerRegistries() []string {
	home, _ := os.UserHomeDir()
	data, err := os.ReadFile(filepath.Join(home, ".docker", "config.json"))
	if err != nil {
		return nil
	}
	var dc struct {
		Auths map[string]interface{} `json:"auths"`
	}
	if json.Unmarshal(data, &dc) != nil || dc.Auths == nil {
		return nil
	}
	regs := make([]string, 0, len(dc.Auths))
	for k := range dc.Auths {
		regs = append(regs, k)
	}
	sort.Strings(regs)
	return regs
}

// 推送模式下的并发控制（Master 推送任务，handleTask 获取信号量）
var (
	sem chan struct{}
	wg  sync.WaitGroup
)

func loadConfig() {
	name := flag.String("name", "", "节点名称（必填）")
	secret := flag.String("secret", "", "通信密钥（必填）")
	master := flag.String("master", "", "Master 地址（必填，如 http://192.168.1.10:8050）")
	workdir := flag.String("workdir", "/data/cicd", "工作目录")
	advertise := flag.String("advertise", "", "Master 回推地址（默认取主机名）")
	heartbeat := flag.Int("heartbeat", 5, "心跳间隔（秒）")
	flag.Parse()

	if *name == "" || *secret == "" || *master == "" {
		fmt.Println("用法: cicd-agent --name <节点名> --secret <密钥> --master <Master地址> [--workdir /data/cicd] [--advertise <IP>]")
		flag.PrintDefaults()
		os.Exit(1)
	}

	adv := *advertise
	if adv == "" {
		adv, _ = os.Hostname()
	}

	cfg = Config{
		MasterURL:     strings.TrimRight(*master, "/"),
		CommSecret:    *secret,
		Name:          *name,
		AdvertiseAddr: adv,
		HeartbeatSec:  *heartbeat,
		MaxConcurrent: 1,    // 固定 1 并发
		WorkDir:       *workdir,
		LogPort:       9090, // 固定端口
	}
	os.MkdirAll(cfg.WorkDir, 0755)
	os.MkdirAll(filepath.Join(cfg.WorkDir, "logs"), 0755)
}

// ─── 主入口 ──────────────────────────────────────────────────────

func main() {
	loadConfig()

	// 服务日志同时写入 stdout（journal）和文件（{WorkDir}/logs/agent.log，供 Master 查看节点日志）
	agentLogPath := filepath.Join(cfg.WorkDir, "logs", "agent.log")
	// O_TRUNC：启动即截断清空旧日志（更新 Agent / 重启后日志从头开始，避免旧日志堆积混淆）
	logFile, err := os.OpenFile(agentLogPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND|os.O_TRUNC, 0644)
	if err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, logFile))
	}
	log.SetFlags(log.Ldate | log.Ltime)

	log.Printf("[Agent] 启动 name=%s master=%s advertise=%s concurrent=%d logPort=%d workdir=%s heartbeat=%ds secret=%s",
		cfg.Name, cfg.MasterURL, cfg.AdvertiseAddr, cfg.MaxConcurrent, cfg.LogPort, cfg.WorkDir, cfg.HeartbeatSec, maskSecret(cfg.CommSecret))

	printRuntimeInfo()

	// 并发信号量（推送模式下由 handleTask 获取）
	sem = make(chan struct{}, cfg.MaxConcurrent)

	// 启动服务器指标采集
	startMetricsCollector()

	// 启动 Docker 构建缓存采集（30s 一次，随心跳上报）
	startDockerCacheCollector()

	// 每天凌晨 1 点清理 3 天前的 Docker 构建缓存
	startDockerCacheCleanup()

	// 采集服务器静态配置（CPU核数/内存总量/磁盘容量），随注册/心跳上报
	collectSysInfo()

	register()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)

	// 日志/任务 HTTP 服务
	go startLogServer()

	// 心跳协程
	go heartbeatLoop(quit)

	<-quit
	log.Println("[Agent] 收到退出信号，等待任务完成...")
	wg.Wait()
	log.Println("[Agent] 已退出")
}
