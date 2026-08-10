package main

// Agent 通讯加密：AES-256-GCM（认证加密）+ gzip 压缩
// 信封格式：{"e": base64( nonce(12) || ciphertext || tag(16) )}
// 明文处理顺序：JSON → gzip 压缩 → AES-GCM 加密 → base64
// 密钥：由共享密钥 cfg.CommSecret 经 SHA-256 派生 32 字节
// 与 Master 端 modules/cicd/services/comm_crypto.py 严格对齐

import (
	"bytes"
	"compress/gzip"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
)

const (
	commNonceLen = 12 // GCM 标准 nonce 长度
	commTagLen   = 16 // GCM 认证标签长度
)

// commKey 由共享密钥经 SHA-256 派生 32 字节 AES 密钥
func commKey() []byte {
	sum := sha256.Sum256([]byte(cfg.CommSecret))
	return sum[:]
}

// encryptEnvelope 将任意对象压缩+加密为信封 {"e": base64}
func encryptEnvelope(obj interface{}) ([]byte, error) {
	plaintext, err := json.Marshal(obj)
	if err != nil {
		return nil, err
	}

	// gzip 压缩
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if _, err := gz.Write(plaintext); err != nil {
		return nil, err
	}
	if err := gz.Close(); err != nil {
		return nil, err
	}

	block, err := aes.NewCipher(commKey())
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, commNonceLen)
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	// Seal 输出 = ciphertext || tag，前置 nonce
	sealed := gcm.Seal(nil, nonce, buf.Bytes(), nil)
	blob := append(nonce, sealed...)

	return json.Marshal(map[string]string{"e": base64.StdEncoding.EncodeToString(blob)})
}

// decryptEnvelope 解密信封 {"e": base64} 到目标对象
func decryptEnvelope(data []byte, out interface{}) error {
	var env map[string]string
	if err := json.Unmarshal(data, &env); err != nil {
		return err
	}
	blob, err := base64.StdEncoding.DecodeString(env["e"])
	if err != nil {
		return err
	}
	if len(blob) < commNonceLen+commTagLen {
		return errors.New("密文长度不足")
	}
	nonce := blob[:commNonceLen]
	sealed := blob[commNonceLen:]

	block, err := aes.NewCipher(commKey())
	if err != nil {
		return err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return err
	}
	compressed, err := gcm.Open(nil, nonce, sealed, nil)
	if err != nil {
		return err
	}

	// gzip 解压
	gz, err := gzip.NewReader(bytes.NewReader(compressed))
	if err != nil {
		return err
	}
	defer gz.Close()
	plaintext, err := io.ReadAll(gz)
	if err != nil {
		return err
	}
	return json.Unmarshal(plaintext, out)
}
