"""剧本杀 Agent 包入口：导入任意子模块前先加载项目根目录的 .env。"""

from dotenv import load_dotenv

# 从调用点向上查找 .env（src/jubensha -> src -> 项目根），不覆盖已存在的环境变量
load_dotenv()
