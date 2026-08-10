package main

// ─── 历史指标 Ring Buffer（零第三方依赖）───
// 在内存中维护最近 100 个采样点（约 5 分钟，3s 间隔）
// 暴露 HTTP 端点 /metrics/history 供 Master 代理访问，用于前端折线图展示

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"
)

// MetricsSample 单个采样点
type MetricsSample struct {
	Timestamp   int64   `json:"t"`  // Unix 时间戳（秒）
	CPULoad     float64 `json:"cpu"`
	MemPercent  float64 `json:"mem"`
	MemUsedGB   float64 `json:"mem_used"`
	MemAvailGB  float64 `json:"mem_avail"`
	DiskReadKB  float64 `json:"disk_read"`
	DiskWriteKB float64 `json:"disk_write"`
	DiskPercent float64 `json:"disk_pct"`
	NetRxKB     float64 `json:"net_rx"`
	NetTxKB     float64 `json:"net_tx"`
	Load1       float64 `json:"load1"`
	Load5       float64 `json:"load5"`
	Load15      float64 `json:"load15"`
}

const metricsHistorySize = 100 // Ring Buffer 容量

var (
	metricsHistory   [metricsHistorySize]MetricsSample
	metricsHistoryMu sync.RWMutex
	metricsHistoryIdx int  // 当前写入位置
	metricsHistoryLen int  // 已填充数量
)

// pushMetricsSample 将当前指标推入 Ring Buffer
func pushMetricsSample() {
	m := currentMetrics()
	sample := MetricsSample{
		Timestamp:   time.Now().Unix(),
		CPULoad:     m.CPULoad,
		MemPercent:  m.MemPercent,
		MemUsedGB:   m.MemUsedGB,
		MemAvailGB:  m.MemAvailGB,
		DiskReadKB:  m.DiskReadKB,
		DiskWriteKB: m.DiskWriteKB,
		DiskPercent: m.DiskPercent,
		NetRxKB:     m.NetRxKB,
		NetTxKB:     m.NetTxKB,
		Load1:       m.Load1,
		Load5:       m.Load5,
		Load15:      m.Load15,
	}

	metricsHistoryMu.Lock()
	metricsHistory[metricsHistoryIdx] = sample
	metricsHistoryIdx = (metricsHistoryIdx + 1) % metricsHistorySize
	if metricsHistoryLen < metricsHistorySize {
		metricsHistoryLen++
	}
	metricsHistoryMu.Unlock()
}

// getMetricsHistory 获取历史指标（按时间顺序）
func getMetricsHistory() []MetricsSample {
	metricsHistoryMu.RLock()
	defer metricsHistoryMu.RUnlock()

	if metricsHistoryLen == 0 {
		return []MetricsSample{}
	}

	result := make([]MetricsSample, metricsHistoryLen)
	// 从最旧的数据开始读取
	start := (metricsHistoryIdx - metricsHistoryLen + metricsHistorySize) % metricsHistorySize
	for i := 0; i < metricsHistoryLen; i++ {
		idx := (start + i) % metricsHistorySize
		result[i] = metricsHistory[idx]
	}
	return result
}

// handleMetricsHistory SSE handler: 每 3 秒推送历史指标
func handleMetricsHistory(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", 500)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")

	// 先推送一次当前数据
	data := getMetricsHistory()
	payload, _ := json.Marshal(data)
	fmt.Fprintf(w, "data: %s\n\n", payload)
	flusher.Flush()

	ticker := time.NewTicker(3 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			data := getMetricsHistory()
			payload, _ := json.Marshal(data)
			fmt.Fprintf(w, "data: %s\n\n", payload)
			flusher.Flush()
		case <-r.Context().Done():
			return
		}
	}
}
