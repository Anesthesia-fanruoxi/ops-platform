package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
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
	logFile, err := os.OpenFile(agentLogPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err == nil {
		log.SetOutput(io.MultiWriter(os.Stdout, logFile))
	}
	log.SetFlags(log.Ldate | log.Ltime)

	log.Printf("[Agent] 启动 name=%s master=%s advertise=%s concurrent=%d logPort=%d",
		cfg.Name, cfg.MasterURL, cfg.AdvertiseAddr, cfg.MaxConcurrent, cfg.LogPort)

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
