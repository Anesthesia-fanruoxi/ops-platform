# -*- coding: utf-8 -*-
"""
Nacos数据库操作服务
用于复制Nacos数据库以初始化namespace
"""
import pymysql


class NacosService:
    """Nacos数据库操作服务"""

    def __init__(self, db_host=None, db_port=None, db_user=None, db_pass=None):
        """
        初始化

        Args:
            db_host: 数据库主机
            db_port: 数据库端口
            db_user: 数据库用户
            db_pass: 数据库密码
        """
        # 连接信息由调用方提供（创建 Nacos 后获得），不做代码默认值
        if not db_host or not db_port or not db_user:
            raise ValueError('缺少 Nacos 数据库连接参数（db_host/db_port/db_user）')
        self.db_host = db_host
        self.db_port = int(db_port)
        self.db_user = db_user
        self.db_pass = db_pass or ''
        self.db_name = 'nacos'

    def _get_connection(self, database=None):
        """获取数据库连接"""
        return pymysql.connect(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pass,
            database=database or self.db_name,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def list_namespaces(self):
        """
        列出所有namespace

        Returns:
            list: namespace列表
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = "SELECT id, namespace_name, namespace_desc, config_count, create_time, update_time FROM namespaces"
                cursor.execute(sql)
                return cursor.fetchall()
        finally:
            conn.close()

    def get_namespace(self, namespace_id):
        """
        获取单个namespace

        Args:
            namespace_id: namespace ID
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = "SELECT * FROM namespaces WHERE id = %s"
                cursor.execute(sql, (namespace_id,))
                return cursor.fetchone()
        finally:
            conn.close()

    def create_namespace(self, namespace_id, namespace_name, namespace_desc=''):
        """
        创建namespace

        Args:
            namespace_id: namespace ID (UUID格式)
            namespace_name: namespace名称
            namespace_desc: 描述
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO namespaces (id, namespace_name, namespace_desc, config_count, create_time, update_time)
                VALUES (%s, %s, %s, 0, NOW(), NOW())
                """
                cursor.execute(sql, (namespace_id, namespace_name, namespace_desc))
                conn.commit()
                return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def copy_namespace(self, source_namespace_id, new_namespace_id, new_namespace_name):
        """
        复制namespace（包括配置数据）

        Args:
            source_namespace_id: 源namespace ID
            new_namespace_id: 新namespace ID
            new_namespace_name: 新namespace名称
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 1. 获取源namespace信息
                cursor.execute("SELECT * FROM namespaces WHERE id = %s", (source_namespace_id,))
                source_ns = cursor.fetchone()
                if not source_ns:
                    raise ValueError(f"Source namespace {source_namespace_id} not found")

                # 2. 创建新namespace
                cursor.execute("""
                INSERT INTO namespaces (id, namespace_name, namespace_desc, config_count, create_time, update_time)
                VALUES (%s, %s, %s, 0, NOW(), NOW())
                """, (new_namespace_id, new_namespace_name, f"Copied from {source_ns['namespace_name']}"))

                # 3. 复制配置数据（config_info表）
                cursor.execute("""
                INSERT INTO config_info (data_id, group_id, content, md5, gmt_create, gmt_modified, src_user, src_ip, app_name, tenant_id, c_desc, c_use, effect, type, c_schema)
                SELECT data_id, group_id, content, md5, NOW(), NOW(), src_user, src_ip, app_name, %s, c_desc, c_use, effect, type, c_schema
                FROM config_info WHERE tenant_id = %s
                """, (new_namespace_id, source_namespace_id))

                copied_configs = cursor.rowcount

                # 4. 复制配置历史（config_info_beta表，如果存在）
                try:
                    cursor.execute("""
                    INSERT INTO config_info_beta (data_id, group_id, content, md5, gmt_create, gmt_modified, src_user, src_ip, tenant_id)
                    SELECT data_id, group_id, content, md5, NOW(), NOW(), src_user, src_ip, %s
                    FROM config_info_beta WHERE tenant_id = %s
                    """, (new_namespace_id, source_namespace_id))
                except:
                    pass  # 表可能不存在

                # 5. 复制灰度发布规则（config_tags_relation表）
                try:
                    cursor.execute("""
                    INSERT INTO config_tags_relation (id, tag_name, tag_type, data_id, group_id, tenant_id, create_time, update_time)
                    SELECT id, tag_name, tag_type, data_id, group_id, %s, NOW(), NOW()
                    FROM config_tags_relation WHERE tenant_id = %s
                    """, (new_namespace_id, source_namespace_id))
                except:
                    pass

                # 6. 更新config_count
                cursor.execute("""
                UPDATE namespaces SET config_count = %s, update_time = NOW() WHERE id = %s
                """, (copied_configs, new_namespace_id))

                conn.commit()

                return {
                    'success': True,
                    'source_namespace': source_ns['namespace_name'],
                    'new_namespace': new_namespace_name,
                    'copied_configs': copied_configs
                }

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def delete_namespace(self, namespace_id):
        """
        删除namespace及其配置

        Args:
            namespace_id: namespace ID
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # 删除配置数据
                cursor.execute("DELETE FROM config_info WHERE tenant_id = %s", (namespace_id,))
                cursor.execute("DELETE FROM config_tags_relation WHERE tenant_id = %s", (namespace_id,))
                try:
                    cursor.execute("DELETE FROM config_info_beta WHERE tenant_id = %s", (namespace_id,))
                except:
                    pass

                # 删除namespace
                cursor.execute("DELETE FROM namespaces WHERE id = %s", (namespace_id,))

                conn.commit()
                return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
