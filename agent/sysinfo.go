package main

// ─── 服务器静态配置采集（零第三方依赖，读 Linux /proc + statfs）───
// 与 metrics.go（实时使用率）不同，此处为低频静态配置：
// - CPU 核数/型号：/proc/cpuinfo
// - 内存总量：/proc/meminfo MemTotal（KB → GB）
// - 磁盘总量/已用：statfs 工作目录所在文件系统
// - OS 信息：/etc/os-release
// - 内核/架构/主机名/运行时长：/proc/version, runtime.GOARCH, os.Hostname(), /proc/uptime
// - Docker 版本：docker version 命令
// 进程启动时采集一次，随注册/心跳上报 Master。

import (
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
)

// SysInfo 服务器配置信息（心跳上报用，静态不变）
type SysInfo struct {
	// 现有字段
	CPUCores    int     // CPU 逻辑核数
	MemTotalGB  float64 // 内存总量 GB
	DiskTotalGB float64 // 磁盘总量 GB（工作目录所在文件系统）
	DiskUsedGB  float64 // 磁盘已用 GB

	// 新增静态信息
	CPUModel         string  // CPU 型号
	CPUPhysicalCores int     // CPU 物理核数
	OSName           string  // 操作系统名称（如 Ubuntu 22.04.3 LTS）
	Kernel           string  // 内核版本
	Arch             string  // 系统架构（x86_64/aarch64）
	Hostname         string  // 主机名
	UptimeSec        int64   // 运行时长（秒）
	DockerVersion    string  // Docker 版本
	DockerPath       string  // Docker 可执行文件路径
	Eth0IP           string  // eth0 网卡 IPv4 地址
	AgentVersion     string  // Agent 版本
}

var sysInfo SysInfo

// collectSysInfo 启动时采集一次服务器配置
func collectSysInfo() {
	sysInfo = SysInfo{
		// 现有字段
		CPUCores:    sampleCPUCores(),
		MemTotalGB:  sampleMemTotalGB(),
		DiskTotalGB: sampleDiskGB(false),
		DiskUsedGB:  sampleDiskGB(true),

		// 新增静态信息
		CPUModel:         sampleCPUModel(),
		CPUPhysicalCores: sampleCPUPhysicalCores(),
		OSName:           sampleOSName(),
		Kernel:           sampleKernel(),
		Arch:             sampleArch(),
		Hostname:         sampleHostname(),
		UptimeSec:        sampleUptime(),
		DockerVersion:    sampleDockerVersion(),
		DockerPath:       dockerBinPath(),
		Eth0IP:           sampleEth0IP(),
		AgentVersion:     agentVersion,
	}
}

// sampleCPUCores 统计 /proc/cpuinfo 的 processor 条目数（逻辑核数）
func sampleCPUCores() int {
	data, err := os.ReadFile("/proc/cpuinfo")
	if err != nil {
		return 0
	}
	count := 0
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "processor") {
			count++
		}
	}
	return count
}

// sampleMemTotalGB 读 /proc/meminfo MemTotal（KB）→ GB（保留 1 位小数）
func sampleMemTotalGB() float64 {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 2 && fields[0] == "MemTotal:" {
			kb, _ := strconv.ParseFloat(fields[1], 64)
			return round1(kb / 1024 / 1024)
		}
	}
	return 0
}

// sampleCPUModel 读 /proc/cpuinfo 第一个 model name 行
func sampleCPUModel() string {
	data, err := os.ReadFile("/proc/cpuinfo")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "model name") {
			parts := strings.SplitN(line, ":", 2)
			if len(parts) == 2 {
				return strings.TrimSpace(parts[1])
			}
		}
	}
	return ""
}

// sampleCPUPhysicalCores 读 /proc/cpuinfo 的 core id 去重统计（物理核数）
func sampleCPUPhysicalCores() int {
	data, err := os.ReadFile("/proc/cpuinfo")
	if err != nil {
		return 0
	}
	seen := make(map[string]bool)
	currentPhysical := ""
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "core id") {
			parts := strings.SplitN(line, ":", 2)
			if len(parts) == 2 {
				currentPhysical = strings.TrimSpace(parts[1])
			}
		} else if strings.HasPrefix(line, "processor") && currentPhysical != "" {
			seen[currentPhysical] = true
			currentPhysical = ""
		}
	}
	return len(seen)
}

// sampleOSName 读 /etc/os-release 的 PRETTY_NAME 行
func sampleOSName() string {
	data, err := os.ReadFile("/etc/os-release")
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(data), "\n") {
		if strings.HasPrefix(line, "PRETTY_NAME=") {
			name := strings.TrimPrefix(line, "PRETTY_NAME=")
			name = strings.Trim(name, "\"")
			return name
		}
	}
	return ""
}

// sampleKernel 读 /proc/version 提取内核版本
func sampleKernel() string {
	data, err := os.ReadFile("/proc/version")
	if err != nil {
		return ""
	}
	// /proc/version 格式: Linux version 5.15.0-86-generic ...
	parts := strings.Fields(string(data))
	if len(parts) >= 3 {
		return parts[2]
	}
	return ""
}

// sampleArch 获取系统架构
func sampleArch() string {
	// 优先使用 runtime.GOARCH
	arch := runtime.GOARCH
	if arch == "amd64" {
		return "x86_64"
	}
	if arch == "arm64" {
		return "aarch64"
	}
	return arch
}

// sampleHostname 获取主机名
func sampleHostname() string {
	h, _ := os.Hostname()
	return h
}

// sampleUptime 读 /proc/uptime 获取运行时长（秒）
func sampleUptime() int64 {
	data, err := os.ReadFile("/proc/uptime")
	if err != nil {
		return 0
	}
	fields := strings.Fields(string(data))
	if len(fields) >= 1 {
		sec, _ := strconv.ParseFloat(fields[0], 64)
		return int64(sec)
	}
	return 0
}

// dockerBinPath 探测 docker 可执行文件路径（优先绝对路径，兼容 systemd 精简 PATH）
func dockerBinPath() string {
	dockerBin := "/usr/bin/docker"
	if _, err := os.Stat(dockerBin); err != nil {
		dockerBin = "docker"
	}
	return dockerBin
}

// sampleDockerVersion 执行 docker version 获取 Docker 版本
func sampleDockerVersion() string {
	out, err := exec.Command(dockerBinPath(), "version", "--format", "{{.Server.Version}}").Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// sampleEth0IP 获取 eth0 网卡 IPv4 地址：优先 ip 命令，回退 ifconfig；
// 无 eth0 时遍历 /sys/class/net 取第一个非回环网卡（兼容 ens*/enp* 命名）
func sampleEth0IP() string {
	candidates := []string{"eth0"}
	if entries, err := os.ReadDir("/sys/class/net"); err == nil {
		for _, e := range entries {
			name := e.Name()
			if name == "lo" || name == "eth0" {
				continue
			}
			candidates = append(candidates, name)
		}
	}
	for _, iface := range candidates {
		// 方式1: ip -4 addr show <iface>
		if out, err := exec.Command("ip", "-4", "addr", "show", iface).Output(); err == nil {
			if ip := parseInetAddr(string(out)); ip != "" {
				return ip
			}
			continue
		}
		// 方式2: ifconfig <iface>
		if out, err := exec.Command("ifconfig", iface).Output(); err == nil {
			if ip := parseInetAddr(string(out)); ip != "" {
				return ip
			}
		}
	}
	return ""
}

// parseInetAddr 从 ip/ifconfig 输出中提取第一个 IPv4 地址
// ip 格式: "inet 192.168.1.10/24 brd ..."；ifconfig 格式: "inet addr:192.168.1.10  Bcast:..."
func parseInetAddr(output string) string {
	for _, line := range strings.Split(output, "\n") {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "inet") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) >= 2 {
			addr := ""
			if strings.HasPrefix(fields[1], "addr:") {
				addr = strings.TrimPrefix(fields[1], "addr:")
			} else {
				addr = strings.SplitN(fields[1], "/", 2)[0]
			}
			if strings.Contains(addr, ".") {
				return addr
			}
		}
	}
	return ""
}
