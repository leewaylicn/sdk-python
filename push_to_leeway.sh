#!/bin/bash

# 推送到leewaylicn账号的脚本
echo "🚀 准备推送到leewaylicn账号..."

echo "请选择推送方式:"
echo "1) 推送到leewaylicn的现有仓库 (需要仓库已存在)"
echo "2) 创建功能分支推送到当前仓库"
echo "3) 显示手动操作指令"
echo ""

read -p "请输入选择 (1-3): " choice

case $choice in
    1)
        echo "📡 添加leewaylicn远程仓库..."
        git remote add leeway https://github.com/leewaylicn/sdk-python.git 2>/dev/null || echo "远程仓库已存在"
        
        echo "🔄 推送到leewaylicn账号..."
        git push leeway main
        
        if [ $? -eq 0 ]; then
            echo "✅ 成功推送到 https://github.com/leewaylicn/sdk-python"
        else
            echo "❌ 推送失败，请检查:"
            echo "   - leewaylicn/sdk-python 仓库是否存在"
            echo "   - 是否有推送权限"
            echo "   - 网络连接是否正常"
        fi
        ;;
        
    2)
        echo "🌿 创建功能分支..."
        git checkout -b feature/customer-service-workflow
        
        echo "🔄 推送功能分支..."
        git push origin feature/customer-service-workflow
        
        if [ $? -eq 0 ]; then
            echo "✅ 成功推送功能分支"
            echo "📋 可以在GitHub上创建Pull Request"
        else
            echo "❌ 推送失败"
        fi
        ;;
        
    3)
        echo "📋 手动操作指令:"
        echo ""
        echo "方案A: 推送到leewaylicn账号 (仓库需要先存在)"
        echo "git remote add leeway https://github.com/leewaylicn/sdk-python.git"
        echo "git push leeway main"
        echo ""
        echo "方案B: 在GitHub上Fork仓库后推送"
        echo "1. 访问 https://github.com/strands-agents/sdk-python"
        echo "2. 点击Fork按钮，Fork到leewaylicn账号"
        echo "3. 执行:"
        echo "   git remote set-url origin https://github.com/leewaylicn/sdk-python.git"
        echo "   git push origin main"
        echo ""
        echo "方案C: 创建新仓库"
        echo "1. 在leewaylicn账号下创建新仓库 'sdk-python'"
        echo "2. 执行:"
        echo "   git remote add leeway https://github.com/leewaylicn/sdk-python.git"
        echo "   git push leeway main"
        ;;
        
    *)
        echo "❌ 无效选择"
        exit 1
        ;;
esac

echo ""
echo "🎉 操作完成!"
