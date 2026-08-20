package main

// ─── Master 通信（注册 / 心跳 / 步骤回调 / 结果上报）──────────────

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sync/atomic"
	"time"
)

func register() {
	m := currentMetrics()
	body := map[string]interface{}{
		"name":          cfg.Name,
		"host":          cfg.AdvertiseAddr,
		"port":          cfg.LogPort,
		"docker_ok":     checkDocker(),
		"cpu_load":      m.CPULoad,
		"mem_percent":   m.MemPercent,
		"disk_read_kb":  m.DiskReadKB,
		"disk_write_kb": m.DiskWriteKB,
		"cpu_cores":     sysInfo.CPUCores,
		"mem_total_gb":  sysInfo.MemTotalGB,
		"disk_total_gb": sysInfo.DiskTotalGB,
		"disk_used_gb":  sysInfo.DiskUsedGB,
		// 新增动态指标
		"load1":        m.Load1,
		"load5":        m.Load5,
		"load15":       m.Load15,
		"net_rx_kb":    m.NetRxKB,
		"net_tx_kb":    m.NetTxKB,
		"disk_percent": m.DiskPercent,
		"mem_used_gb":  m.MemUsedGB,
		"mem_avail_gb": m.MemAvailGB,
		// Docker 构建缓存大小（30s 采集一次）
		"docker_cache_size": m.DockerCache,
		// 静态系统信息 JSON
		"sys_info": buildSysInfoJSON(),
		// 当前运行任务数（Master 并发依据，Agent 自行上报）
		"running_count": atomic.LoadInt32(&runningCount),
	}
	resp := postEncrypted("/api/cicd/agent/register", body)
	if resp != nil {
		log.Printf("[Agent] 注册成功 agent_id=%v", resp["agent_id"])
	} else {
		log.Println("[Agent] 注册失败（将在心跳时重试）")
	}
}

func heartbeatLoop(quit <-chan os.Signal) {
	ticker := time.NewTicker(time.Duration(cfg.HeartbeatSec) * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-quit:
			return
		case <-ticker.C:
			m := currentMetrics()
			body := map[string]interface{}{
				"name":          cfg.Name,
				"port":          cfg.LogPort,
				"docker_ok":     checkDocker(),
				"cpu_load":      m.CPULoad,
				"mem_percent":   m.MemPercent,
				"disk_read_kb":  m.DiskReadKB,
				"disk_write_kb": m.DiskWriteKB,
				"cpu_cores":     sysInfo.CPUCores,
				"mem_total_gb":  sysInfo.MemTotalGB,
				"disk_total_gb": sysInfo.DiskTotalGB,
				"disk_used_gb":  sysInfo.DiskUsedGB,
				// 新增动态指标
				"load1":        m.Load1,
				"load5":        m.Load5,
				"load15":       m.Load15,
				"net_rx_kb":    m.NetRxKB,
				"net_tx_kb":    m.NetTxKB,
				"disk_percent": m.DiskPercent,
				"mem_used_gb":  m.MemUsedGB,
				"mem_avail_gb": m.MemAvailGB,
				// Docker 构建缓存大小（30s 采集一次）
				"docker_cache_size": m.DockerCache,
				// 静态系统信息 JSON
				"sys_info": buildSysInfoJSON(),
				// 当前运行任务数（Master 并发依据，Agent 自行上报）
				"running_count": atomic.LoadInt32(&runningCount),
			}
			postEncrypted("/api/cicd/agent/heartbeat", body)
		}
	}
}

// buildSysInfoJSON 构建静态系统信息 JSON 字符串
func buildSysInfoJSON() string {
	info := map[string]interface{}{
		"os_name":            sysInfo.OSName,
		"kernel":             sysInfo.Kernel,
		"arch":               sysInfo.Arch,
		"hostname":           sysInfo.Hostname,
		"cpu_model":          sysInfo.CPUModel,
		"cpu_physical_cores": sysInfo.CPUPhysicalCores,
		"docker_version":     sysInfo.DockerVersion,
		"docker_path":        sysInfo.DockerPath,
	}
	data, _ := json.Marshal(info)
	return string(data)
}

// sendStep 回调步骤状态到 Master，返回 cancel_requested
func sendStep(buildID, stepNo int, stepKey, status, errMsg string) bool {
	body := map[string]interface{}{
		"name":     cfg.Name,
		"step_no":  stepNo,
		"step_key": stepKey,
		"status":   status,
		"error":    errMsg,
	}
	resp := postEncrypted(fmt.Sprintf("/api/cicd/agent/build/%d/step", buildID), body)
	if resp != nil {
		if cr, ok := resp["cancel_requested"].(bool); ok {
			return cr
		}
	}
	return false
}

func sendResult(buildID int, status, digest, errMsg string) {
	body := map[string]interface{}{
		"name":         cfg.Name,
		"status":       status,
		"image_digest": digest,
		"error":        errMsg,
	}
	path := fmt.Sprintf("/api/cicd/agent/build/%d/result", buildID)
	// 构建结果回调是关键链路：失败会导致构建状态停在 running，UI 一直显示「构建中」
	// 重试 3 次（3s/6s/12s 指数退避），避免单次网络/解密异常导致状态卡死
	for attempt := 0; attempt < 3; attempt++ {
		result := postEncrypted(path, body)
		if result != nil {
			return
		}
		wait := time.Duration(3<<uint(attempt)) * time.Second // 3s, 6s, 12s
		log.Printf("[HTTP] sendResult build#%d 第 %d 次失败，%v 后重试", buildID, attempt+1, wait)
		time.Sleep(wait)
	}
	log.Printf("[HTTP] sendResult build#%d 重试 3 次均失败，构建状态可能无法及时更新", buildID)
}

// postEncrypted 加密请求体（AES-GCM+gzip 信封）并解密响应信封
func postEncrypted(path string, body interface{}) map[string]interface{} {
	payload, err := encryptEnvelope(body)
	if err != nil {
		log.Printf("[HTTP] 加密 %s 请求失败: %v", path, err)
		return nil
	}
	resp, err := http.Post(cfg.MasterURL+path, "application/json", bytes.NewReader(payload))
	if err != nil {
		log.Printf("[HTTP] POST %s 失败: %v", path, err)
		return nil
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	var result map[string]interface{}
	if err := decryptEnvelope(data, &result); err != nil {
		log.Printf("[HTTP] 解密 %s 响应失败: %v", path, err)
		return nil
	}
	return result
}
