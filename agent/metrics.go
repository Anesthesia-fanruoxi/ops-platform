package main

// 服务器指标采集（零第三方依赖，读 Linux /proc）：
// - CPU 使用率：/proc/stat 两次采样差值
// - 内存使用率/已用/可用：/proc/meminfo
// - 磁盘IO：/proc/diskstats 累计扇区(512B)差值 → 读/写 KB/s
// - 系统负载：/proc/loadavg
// - 网络流量：/proc/net/dev 差值 → 收/发 KB/s
// - 磁盘使用率：sysInfo 中计算
// - Docker 构建缓存大小：独立协程每 30s 执行 docker system df（心跳上报）
// 后台每 3s 采样一次，心跳读取最新快照。

import (
	"context"
	"log"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Metrics 服务器指标快照（心跳上报用）
type Metrics struct {
	// 现有字段
	CPULoad     float64 // CPU 使用率 %
	MemPercent  float64 // 内存使用率 %
	DiskReadKB  float64 // 磁盘读 KB/s
	DiskWriteKB float64 // 磁盘写 KB/s

	// 新增动态指标
	Load1       float64 // 系统负载 1 min
	Load5       float64 // 系统负载 5 min
	Load15      float64 // 系统负载 15 min
	NetRxKB     float64 // 网络接收 KB/s
	NetTxKB     float64 // 网络发送 KB/s
	DiskPercent float64 // 磁盘使用率 %
	MemUsedGB   float64 // 内存已用 GB
	MemAvailGB  float64 // 内存可用 GB
	DockerCache string  // Docker 构建缓存大小（如 12.3GB / 0B）
}

var (
	metricsMu      sync.RWMutex
	latestMetrics  Metrics
	lastCPUTotal   uint64
	lastCPUIdle    uint64
	lastReadSec    uint64
	lastWriteSec   uint64
	lastNetRx      uint64
	lastNetTx      uint64
	lastSampleTime time.Time
)

// startMetricsCollector 初始化基线并启动后台采样协程（每 3s）
func startMetricsCollector() {
	sampleCPU() // 建立 CPU 基线
	lastReadSec, lastWriteSec = readDiskSectors()
	lastNetRx, lastNetTx = readNetBytes()
	lastSampleTime = time.Now()

	go func() {
		ticker := time.NewTicker(3 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			collectOnce()
		}
	}()
}

// startDockerCacheCollector 独立协程采集 Docker 构建缓存大小（立即一次 + 每 30s）
// 命令耗时秒级，不放入 3s 主采样循环，结果写入 Metrics 供心跳上报
func startDockerCacheCollector() {
	sampleDockerCache()
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			sampleDockerCache()
		}
	}()
}

// sampleDockerCache 执行 docker system df 获取 Build Cache 大小
// 说明：不用 --filter（旧版/新版 docker 支持不一致），输出全量行后解析 Build Cache 行
func sampleDockerCache() {
	// 优先用绝对路径，兼容 systemd 精简 PATH
	dockerBin := "/usr/bin/docker"
	if _, err := os.Stat(dockerBin); err != nil {
		dockerBin = "docker"
	}
	args := []string{"system", "df", "--format", "{{.Type}}|{{.Size}}"}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, dockerBin, args...).CombinedOutput()
	// 上次成功的值：命令失败或解析不到时保留，避免真实值被 0B 误覆盖
	old := currentMetrics().DockerCache
	if old == "" {
		old = "0B"
	}
	size := old
	if err == nil {
		for _, line := range strings.Split(string(out), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			parts := strings.SplitN(line, "|", 2)
			if len(parts) == 2 && strings.TrimSpace(parts[0]) == "Build Cache" {
				size = strings.TrimSpace(parts[1])
				if size == "" {
					size = "0B"
				}
				break
			}
		}
	}
	metricsMu.Lock()
	latestMetrics.DockerCache = size
	metricsMu.Unlock()
}

// startDockerCacheCleanup 每天凌晨 1 点清理 3 天前的 Docker 构建缓存
// （--filter until=72h 不会误删使用中的缓存，构建期间执行也安全）
func startDockerCacheCleanup() {
	go func() {
		for {
			now := time.Now()
			next := time.Date(now.Year(), now.Month(), now.Day(), 1, 0, 0, 0, now.Location())
			if !next.After(now) {
				next = next.Add(24 * time.Hour)
			}
			time.Sleep(next.Sub(now))
			runDockerCacheCleanup()
			time.Sleep(24 * time.Hour)
		}
	}()
}

// runDockerCacheCleanup 执行 docker builder prune：清理 3 天前（72h）的构建缓存
func runDockerCacheCleanup() {
	dockerBin := "/usr/bin/docker"
	if _, err := os.Stat(dockerBin); err != nil {
		dockerBin = "docker"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()
	out, err := exec.CommandContext(
		ctx, dockerBin, "builder", "prune", "--filter", "until=72h", "-f",
	).CombinedOutput()
	if err != nil {
		log.Printf("[CacheCleanup] 清理失败: %v", err)
		return
	}
	msg := strings.TrimSpace(string(out))
	if msg == "" {
		msg = "无 3 天前缓存可清理"
	}
	log.Printf("[CacheCleanup] 清理完成: %s", msg)
}

func collectOnce() {
	now := time.Now()
	elapsed := now.Sub(lastSampleTime).Seconds()
	if elapsed <= 0 {
		elapsed = 1
	}

	cpu := sampleCPU()
	memPercent, memUsedGB, memAvailGB := sampleMemDetail()
	readKB, writeKB := sampleDiskRate(elapsed)
	netRxKB, netTxKB := sampleNetRate(elapsed)
	load1, load5, load15 := sampleLoadAvg()
	diskPercent := calcDiskPercent()
	lastSampleTime = now

	metricsMu.Lock()
	latestMetrics = Metrics{
		// 现有字段
		CPULoad:     round1(cpu),
		MemPercent:  round1(memPercent),
		DiskReadKB:  round1(readKB),
		DiskWriteKB: round1(writeKB),
		// 新增动态指标
		Load1:       load1,
		Load5:       load5,
		Load15:      load15,
		NetRxKB:     round1(netRxKB),
		NetTxKB:     round1(netTxKB),
		DiskPercent: diskPercent,
		MemUsedGB:   round1(memUsedGB),
		MemAvailGB:  round1(memAvailGB),
		// Docker 构建缓存由独立 30s 协程维护，主采样不能覆盖为空
		DockerCache: latestMetrics.DockerCache,
	}
	metricsMu.Unlock()

	// 推入历史指标 Ring Buffer
	pushMetricsSample()
}

func currentMetrics() Metrics {
	metricsMu.RLock()
	defer metricsMu.RUnlock()
	return latestMetrics
}

// sampleCPU 读 /proc/stat 计算两次采样间的 CPU 使用率
func sampleCPU() float64 {
	data, err := os.ReadFile("/proc/stat")
	if err != nil {
		return 0
	}
	line := strings.SplitN(string(data), "\n", 2)[0]
	fields := strings.Fields(line)
	if len(fields) < 5 || fields[0] != "cpu" {
		return 0
	}
	var total, idle uint64
	for i := 1; i < len(fields); i++ {
		v, _ := strconv.ParseUint(fields[i], 10, 64)
		total += v
		if i == 4 || i == 5 { // idle + iowait
			idle += v
		}
	}
	cpu := 0.0
	if lastCPUTotal > 0 && total > lastCPUTotal {
		dTotal := total - lastCPUTotal
		dIdle := idle - lastCPUIdle
		cpu = float64(dTotal-dIdle) / float64(dTotal) * 100
	}
	lastCPUTotal = total
	lastCPUIdle = idle
	return cpu
}

// sampleMemDetail 读 /proc/meminfo 计算内存使用率、已用GB、可用GB
func sampleMemDetail() (percent, usedGB, availGB float64) {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0, 0, 0
	}
	var total, avail float64
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		v, _ := strconv.ParseFloat(fields[1], 64)
		switch fields[0] {
		case "MemTotal:":
			total = v
		case "MemAvailable:":
			avail = v
		}
	}
	if total <= 0 {
		return 0, 0, 0
	}
	percent = (total - avail) / total * 100
	usedGB = (total - avail) / 1024 / 1024
	availGB = avail / 1024 / 1024
	return percent, usedGB, availGB
}

// readDiskSectors 汇总 /proc/diskstats 所有设备的读写扇区数
func readDiskSectors() (read, write uint64) {
	data, err := os.ReadFile("/proc/diskstats")
	if err != nil {
		return 0, 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) < 10 {
			continue
		}
		r, _ := strconv.ParseUint(fields[5], 10, 64) // rd_sectors
		w, _ := strconv.ParseUint(fields[9], 10, 64) // wr_sectors
		read += r
		write += w
	}
	return read, write
}

// sampleDiskRate 计算两次采样间的读写 KB/s（扇区=512B）
func sampleDiskRate(elapsed float64) (readKB, writeKB float64) {
	r, w := readDiskSectors()
	if r >= lastReadSec && lastReadSec > 0 {
		readKB = float64(r-lastReadSec) * 512 / 1024 / elapsed
	}
	if w >= lastWriteSec && lastWriteSec > 0 {
		writeKB = float64(w-lastWriteSec) * 512 / 1024 / elapsed
	}
	lastReadSec, lastWriteSec = r, w
	return readKB, writeKB
}

func round1(v float64) float64 {
	return float64(int(v*10+0.5)) / 10
}

// sampleLoadAvg 读 /proc/loadavg 获取系统负载 1/5/15 min
func sampleLoadAvg() (load1, load5, load15 float64) {
	data, err := os.ReadFile("/proc/loadavg")
	if err != nil {
		return 0, 0, 0
	}
	fields := strings.Fields(string(data))
	if len(fields) >= 3 {
		load1, _ = strconv.ParseFloat(fields[0], 64)
		load5, _ = strconv.ParseFloat(fields[1], 64)
		load15, _ = strconv.ParseFloat(fields[2], 64)
	}
	return load1, load5, load15
}

// readNetBytes 汇总 /proc/net/dev 所有非 loopback 网卡的收发字节数
func readNetBytes() (rx, tx uint64) {
	data, err := os.ReadFile("/proc/net/dev")
	if err != nil {
		return 0, 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		// 跳过表头和 loopback
		if strings.Contains(line, "lo:") || !strings.Contains(line, ":") {
			continue
		}
		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}
		fields := strings.Fields(parts[1])
		if len(fields) >= 10 {
			r, _ := strconv.ParseUint(fields[0], 10, 64) // rx_bytes
			t, _ := strconv.ParseUint(fields[8], 10, 64) // tx_bytes
			rx += r
			tx += t
		}
	}
	return rx, tx
}

// sampleNetRate 计算两次采样间的网络收发 KB/s
func sampleNetRate(elapsed float64) (rxKB, txKB float64) {
	rx, tx := readNetBytes()
	if rx >= lastNetRx && lastNetRx > 0 {
		rxKB = float64(rx-lastNetRx) / 1024 / elapsed
	}
	if tx >= lastNetTx && lastNetTx > 0 {
		txKB = float64(tx-lastNetTx) / 1024 / elapsed
	}
	lastNetRx, lastNetTx = rx, tx
	return rxKB, txKB
}

// calcDiskPercent 计算磁盘使用率
func calcDiskPercent() float64 {
	if sysInfo.DiskTotalGB <= 0 {
		return 0
	}
	return round1(sysInfo.DiskUsedGB / sysInfo.DiskTotalGB * 100)
}
