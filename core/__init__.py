import pymysql

pymysql.version_info = (2, 2, 1, "final", 0)  # Esto engaña a Django sobre la versión
pymysql.install_as_MySQLdb()