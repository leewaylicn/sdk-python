#!/bin/bash

# Git提交脚本 - 提交到leewaylicn账号
# 使用方法: ./commit_to_github.sh

echo "🚀 开始提交代码到GitHub..."

# 检查当前目录
echo "📁 当前目录: $(pwd)"

# 添加所有修改的文件
echo "📝 添加修改的文件..."
git add customer_service_workflow.py
git add utility_agent.py
git add auto_mock_model.py
git add smart_input_generator.py

# 添加新的测试文件
echo "🧪 添加测试文件..."
git add test_*.py 2>/dev/null || echo "没有找到测试文件"
git add *test*.py 2>/dev/null || echo "没有找到其他测试文件"
git add debug_*.py 2>/dev/null || echo "没有找到调试文件"
git add demo_*.py 2>/dev/null || echo "没有找到演示文件"

# 添加文档文件
echo "📚 添加文档文件..."
git add *.md 2>/dev/null || echo "没有找到新的文档文件"

# 添加会话管理相关文件
echo "💾 添加会话管理文件..."
git add src/strands/session/ddb_session_manager.py 2>/dev/null || echo "会话管理文件已存在"
git add tests/strands/session/test_ddb_session_manager.py 2>/dev/null || echo "会话管理测试文件已存在"
git add tests_integ/test_ddb_session.py 2>/dev/null || echo "集成测试文件已存在"

# 显示将要提交的文件
echo "📋 将要提交的文件:"
git status --porcelain

# 创建提交
echo "💬 创建提交..."
git commit -m "feat: 实现客服工作流和UtilityAgent功能

主要更新:
- 添加customer_service_workflow.py: 多Agent客服工作流系统
- 添加utility_agent.py: UtilityAgent实用代理类
- 添加auto_mock_model.py: 自动模拟模型
- 添加smart_input_generator.py: 智能输入生成器
- 实现人工干预(Human-in-the-loop)功能
- 支持DynamoDB会话管理
- 添加comprehensive测试套件

技术特性:
- 多Agent协作工作流
- 情感分析和意图识别
- 知识库查询和人工交接
- UtilityAgent优化工具调用
- 会话持久化支持"

echo "✅ 提交完成!"

# 显示提交信息
echo "📊 最新提交信息:"
git log --oneline -1

echo ""
echo "🔄 接下来的步骤:"
echo "1. 如果要推送到当前远程仓库 (strands-agents/sdk-python):"
echo "   git push origin main"
echo ""
echo "2. 如果要推送到leewaylicn账号的仓库:"
echo "   a) 先添加新的远程仓库:"
echo "      git remote add leeway https://github.com/leewaylicn/sdk-python.git"
echo "   b) 推送到新仓库:"
echo "      git push leeway main"
echo ""
echo "3. 或者创建新的仓库分支:"
echo "   git checkout -b feature/customer-service-workflow"
echo "   git push origin feature/customer-service-workflow"

echo ""
echo "🎉 脚本执行完成!"
