//go:build !linux

package main

// ─── 磁盘容量采集（非 Linux 平台占位：Agent 部署目标为 Linux，
// 此处仅保证本地开发/语法验证可编译，返回 0 不参与实际运行）───

func sampleDiskGB(used bool) float64 {
	return 0
}
