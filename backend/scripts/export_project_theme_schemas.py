"""输出主题Schema，供前端及维护工具消费或检查已提交产物。"""

import json

from yuxi.services.project_theme_contract import contract_schemas

if __name__ == "__main__":
    print(json.dumps(contract_schemas(), ensure_ascii=False, indent=2))
