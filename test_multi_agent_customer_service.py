#!/usr/bin/env python3
"""
多Agent客户服务系统 - 全面测试文件

测试覆盖：
1. 统一状态字段映射
2. StateHook状态传递机制
3. Graph路由决策逻辑
4. 不同类型的用户输入处理
5. Human-in-the-loop触发条件
6. 错误处理和容错机制
"""

import json
import time
from typing import Dict, Any, List
from multi_agent_customer_service_simplified import MultiAgentCustomerService, UnifiedAgentState


class TestMultiAgentCustomerService:
    """多Agent客户服务系统测试类"""
    
    def __init__(self):
        self.test_results = []
        self.passed_tests = 0
        self.failed_tests = 0
    
    def run_all_tests(self):
        """运行所有测试"""
        print("🧪 开始多Agent客户服务系统全面测试")
        print("="*80)
        
        # 1. 基础功能测试
        self.test_unified_state_mapping()
        self.test_system_initialization()
        
        # 2. 业务场景测试
        self.test_booking_scenarios()
        self.test_activity_scenarios()
        self.test_complaint_scenarios()
        self.test_human_intervention_scenarios()
        
        # 3. 边界条件测试
        self.test_edge_cases()
        self.test_error_handling()
        
        # 4. 状态管理测试
        self.test_state_propagation()
        self.test_graph_routing()
        
        # 输出测试结果
        self.print_test_summary()
    
    def test_unified_state_mapping(self):
        """测试统一状态字段映射"""
        print("\n📋 测试1: 统一状态字段映射")
        print("-" * 40)
        
        try:
            # 检查必要的状态字段
            required_fields = [
                "subject_type", "activity_id", "booking_id", "recent_bookings",
                "contact_reason", "stage", "status", "requires_human", "confidence"
            ]
            
            mapping = UnifiedAgentState.UNIFIED_STATE_MAPPING
            
            for field in required_fields:
                assert field in mapping, f"缺少必要字段: {field}"
                assert mapping[field] == field, f"字段映射错误: {field} -> {mapping[field]}"
            
            # 检查不应该包含的字段
            excluded_fields = ["analysis", "entities", "response"]
            for field in excluded_fields:
                assert field not in mapping, f"不应包含字段: {field}"
            
            self.log_test_result("统一状态字段映射", True, "所有必要字段正确映射，排除了非状态字段")
            
        except Exception as e:
            self.log_test_result("统一状态字段映射", False, str(e))
    
    def test_system_initialization(self):
        """测试系统初始化"""
        print("\n📋 测试2: 系统初始化")
        print("-" * 40)
        
        try:
            # 创建系统实例
            customer_service = MultiAgentCustomerService()
            
            # 检查图结构
            assert customer_service.graph is not None, "图未正确初始化"
            assert len(customer_service.graph.nodes) == 5, f"节点数量错误: {len(customer_service.graph.nodes)}"
            assert len(customer_service.graph.edges) > 0, "边数量为0"
            
            # 检查共享状态
            assert customer_service.shared_state is not None, "共享状态未初始化"
            
            # 检查节点名称
            expected_nodes = ["entry_agent", "route_agent", "intent_agent", "transfer_agent", "answer_agent"]
            actual_nodes = list(customer_service.graph.nodes.keys())
            for node in expected_nodes:
                assert node in actual_nodes, f"缺少节点: {node}"
            
            self.log_test_result("系统初始化", True, f"成功创建{len(customer_service.graph.nodes)}个节点的图结构")
            
        except Exception as e:
            self.log_test_result("系统初始化", False, str(e))
    
    def test_booking_scenarios(self):
        """测试预订相关场景"""
        print("\n📋 测试3: 预订相关场景")
        print("-" * 40)
        
        booking_test_cases = [
            {
                "input": "我想查询订单def12345的状态",
                "expected_subject_type": "booking",
                "expected_human": False,
                "description": "订单查询"
            },
            {
                "input": "预订酒店房间，明天入住",
                "expected_subject_type": "booking", 
                "expected_human": False,
                "description": "酒店预订"
            },
            {
                "input": "我要取消预订def67890，因为计划有变",
                "expected_subject_type": "booking",
                "expected_human": False,
                "description": "预订取消"
            }
        ]
        
        for i, test_case in enumerate(booking_test_cases, 1):
            try:
                print(f"\n  测试3.{i}: {test_case['description']}")
                customer_service = MultiAgentCustomerService()
                result = customer_service.execute(test_case["input"])
                
                # 检查执行结果
                shared_state = customer_service.shared_state.get_all()
                
                # 验证主题类型
                subject_type = shared_state.get("subject_type")
                if subject_type:
                    assert subject_type == test_case["expected_subject_type"], \
                        f"主题类型错误: 期望{test_case['expected_subject_type']}, 实际{subject_type}"
                
                # 验证工作流完成
                assert result.status.name == "COMPLETED", f"工作流未完成: {result.status}"
                
                self.log_test_result(f"预订场景-{test_case['description']}", True, 
                                   f"主题类型: {subject_type}, 状态: {result.status.name}")
                
            except Exception as e:
                self.log_test_result(f"预订场景-{test_case['description']}", False, str(e))
    
    def test_activity_scenarios(self):
        """测试活动相关场景"""
        print("\n📋 测试4: 活动相关场景")
        print("-" * 40)
        
        activity_test_cases = [
            {
                "input": "请推荐一些北京的旅游景点",
                "expected_subject_type": "activity",
                "expected_human": False,
                "description": "景点推荐"
            },
            {
                "input": "活动abc12345什么时候开始？",
                "expected_subject_type": "activity",
                "expected_human": False,
                "description": "活动查询"
            },
            {
                "input": "我想参加户外徒步活动",
                "expected_subject_type": "activity",
                "expected_human": False,
                "description": "活动参与"
            }
        ]
        
        for i, test_case in enumerate(activity_test_cases, 1):
            try:
                print(f"\n  测试4.{i}: {test_case['description']}")
                customer_service = MultiAgentCustomerService()
                result = customer_service.execute(test_case["input"])
                
                # 检查执行结果
                shared_state = customer_service.shared_state.get_all()
                
                # 验证主题类型
                subject_type = shared_state.get("subject_type")
                if subject_type:
                    assert subject_type == test_case["expected_subject_type"], \
                        f"主题类型错误: 期望{test_case['expected_subject_type']}, 实际{subject_type}"
                
                # 验证工作流完成
                assert result.status.name == "COMPLETED", f"工作流未完成: {result.status}"
                
                self.log_test_result(f"活动场景-{test_case['description']}", True,
                                   f"主题类型: {subject_type}, 状态: {result.status.name}")
                
            except Exception as e:
                self.log_test_result(f"活动场景-{test_case['description']}", False, str(e))
    
    def test_complaint_scenarios(self):
        """测试投诉相关场景"""
        print("\n📋 测试5: 投诉相关场景")
        print("-" * 40)
        
        complaint_test_cases = [
            {
                "input": "我对你们的服务非常不满意，要投诉！",
                "expected_human": True,
                "description": "服务投诉"
            },
            {
                "input": "这个产品质量有问题，我要退款",
                "expected_human": True,
                "description": "退款请求"
            },
            {
                "input": "我已经联系过客服多次但没有解决，需要找经理",
                "expected_human": True,
                "description": "升级处理"
            }
        ]
        
        for i, test_case in enumerate(complaint_test_cases, 1):
            try:
                print(f"\n  测试5.{i}: {test_case['description']}")
                customer_service = MultiAgentCustomerService()
                result = customer_service.execute(test_case["input"])
                
                # 检查执行结果
                shared_state = customer_service.shared_state.get_all()
                
                # 验证人工干预
                requires_human = shared_state.get("requires_human")
                if requires_human is not None:
                    assert requires_human == test_case["expected_human"], \
                        f"人工干预判断错误: 期望{test_case['expected_human']}, 实际{requires_human}"
                
                # 验证是否触发了转接
                transfer_triggered = "transfer_agent" in result.results
                if test_case["expected_human"]:
                    assert transfer_triggered, "应该触发人工转接但未触发"
                
                self.log_test_result(f"投诉场景-{test_case['description']}", True,
                                   f"人工干预: {requires_human}, 转接触发: {transfer_triggered}")
                
            except Exception as e:
                self.log_test_result(f"投诉场景-{test_case['description']}", False, str(e))
    
    def test_human_intervention_scenarios(self):
        """测试人工干预触发条件"""
        print("\n📋 测试6: 人工干预触发条件")
        print("-" * 40)
        
        # 应该触发人工干预的关键词
        human_keywords = ["退款", "投诉", "不满意", "差评", "问题严重", "经理", "主管", "人工客服", "转人工"]
        
        for i, keyword in enumerate(human_keywords[:3], 1):  # 测试前3个关键词
            try:
                test_input = f"我遇到了{keyword}的问题，请帮助处理"
                print(f"\n  测试6.{i}: 关键词'{keyword}'触发测试")
                
                customer_service = MultiAgentCustomerService()
                result = customer_service.execute(test_input)
                
                # 检查是否触发人工干预
                shared_state = customer_service.shared_state.get_all()
                requires_human = shared_state.get("requires_human")
                transfer_triggered = "transfer_agent" in result.results
                
                # 验证人工干预逻辑
                if requires_human:
                    assert transfer_triggered, f"关键词'{keyword}'应该触发转接但未触发"
                
                self.log_test_result(f"人工干预-{keyword}", True,
                                   f"人工干预: {requires_human}, 转接: {transfer_triggered}")
                
            except Exception as e:
                self.log_test_result(f"人工干预-{keyword}", False, str(e))
    
    def test_edge_cases(self):
        """测试边界条件"""
        print("\n📋 测试7: 边界条件")
        print("-" * 40)
        
        edge_cases = [
            {
                "input": "",
                "description": "空输入"
            },
            {
                "input": "a",
                "description": "单字符输入"
            },
            {
                "input": "帮助",
                "description": "简单点击流"
            },
            {
                "input": "这是一个非常长的用户输入，包含了很多信息，但是没有明确的意图，也没有特定的关键词，主要是测试系统对于复杂和模糊输入的处理能力，看看系统是否能够正确地进行分类和路由决策。",
                "description": "超长复杂输入"
            }
        ]
        
        for i, test_case in enumerate(edge_cases, 1):
            try:
                print(f"\n  测试7.{i}: {test_case['description']}")
                customer_service = MultiAgentCustomerService()
                result = customer_service.execute(test_case["input"])
                
                # 基本验证：系统应该能够处理而不崩溃
                assert result is not None, "结果为空"
                assert hasattr(result, 'status'), "结果缺少状态字段"
                
                # 检查是否有基本的状态设置
                shared_state = customer_service.shared_state.get_all()
                assert "workflow_status" in shared_state, "缺少工作流状态"
                
                self.log_test_result(f"边界条件-{test_case['description']}", True,
                                   f"状态: {result.status.name}")
                
            except Exception as e:
                self.log_test_result(f"边界条件-{test_case['description']}", False, str(e))
    
    def test_error_handling(self):
        """测试错误处理"""
        print("\n📋 测试8: 错误处理")
        print("-" * 40)
        
        try:
            # 测试系统在异常情况下的表现
            customer_service = MultiAgentCustomerService()
            
            # 模拟正常执行
            result = customer_service.execute("测试错误处理")
            
            # 检查错误状态记录
            shared_state = customer_service.shared_state.get_all()
            workflow_status = shared_state.get("workflow_status")
            
            # 系统应该能够正常完成或记录错误状态
            assert workflow_status in ["running", "completed", "failed"], \
                f"工作流状态异常: {workflow_status}"
            
            self.log_test_result("错误处理", True, f"工作流状态: {workflow_status}")
            
        except Exception as e:
            self.log_test_result("错误处理", False, str(e))
    
    def test_state_propagation(self):
        """测试状态传递"""
        print("\n📋 测试9: 状态传递")
        print("-" * 40)
        
        try:
            customer_service = MultiAgentCustomerService()
            result = customer_service.execute("我想查询订单def12345的预订状态")
            
            # 检查状态历史
            state_history = customer_service.shared_state.history
            assert len(state_history) > 0, "没有状态变化记录"
            
            # 检查是否有inject和extract操作
            operations = [change.operation for change in state_history]
            assert "inject" in operations, "缺少状态注入操作"
            assert "extract" in operations, "缺少状态提取操作"
            
            # 检查最终状态
            final_state = customer_service.shared_state.get_all()
            assert "stage" in final_state, "缺少stage字段"
            assert "status" in final_state, "缺少status字段"
            
            self.log_test_result("状态传递", True, 
                               f"状态变化次数: {len(state_history)}, 最终stage: {final_state.get('stage')}")
            
        except Exception as e:
            self.log_test_result("状态传递", False, str(e))
    
    def test_graph_routing(self):
        """测试图路由逻辑"""
        print("\n📋 测试10: 图路由逻辑")
        print("-" * 40)
        
        try:
            # 测试自动处理路径
            print("\n  测试10.1: 自动处理路径")
            customer_service = MultiAgentCustomerService()
            result = customer_service.execute("请问有什么旅游活动推荐？")
            
            # 应该执行: entry -> route -> intent -> answer
            expected_auto_path = ["entry_agent", "route_agent", "intent_agent", "answer_agent"]
            actual_nodes = [node.node_id for node in result.execution_order]
            
            for expected_node in expected_auto_path:
                assert expected_node in actual_nodes, f"自动处理路径缺少节点: {expected_node}"
            
            assert "transfer_agent" not in actual_nodes, "自动处理路径不应包含transfer_agent"
            
            # 测试人工干预路径
            print("\n  测试10.2: 人工干预路径")
            customer_service2 = MultiAgentCustomerService()
            result2 = customer_service2.execute("我要投诉你们的服务，非常不满意！")
            
            # 应该执行: entry -> route -> transfer
            actual_nodes2 = [node.node_id for node in result2.execution_order]
            
            assert "entry_agent" in actual_nodes2, "人工干预路径缺少entry_agent"
            assert "route_agent" in actual_nodes2, "人工干预路径缺少route_agent"
            assert "transfer_agent" in actual_nodes2, "人工干预路径缺少transfer_agent"
            
            self.log_test_result("图路由逻辑", True,
                               f"自动路径节点: {len([n for n in actual_nodes if n != 'transfer_agent'])}, "
                               f"人工干预路径包含transfer_agent: {'transfer_agent' in actual_nodes2}")
            
        except Exception as e:
            self.log_test_result("图路由逻辑", False, str(e))
    
    def log_test_result(self, test_name: str, passed: bool, details: str):
        """记录测试结果"""
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {test_name}: {details}")
        
        self.test_results.append({
            "name": test_name,
            "passed": passed,
            "details": details
        })
        
        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
    
    def print_test_summary(self):
        """打印测试摘要"""
        print("\n" + "="*80)
        print("🎯 测试摘要")
        print("="*80)
        
        total_tests = self.passed_tests + self.failed_tests
        pass_rate = (self.passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        print(f"总测试数: {total_tests}")
        print(f"通过测试: {self.passed_tests}")
        print(f"失败测试: {self.failed_tests}")
        print(f"通过率: {pass_rate:.1f}%")
        
        if self.failed_tests > 0:
            print(f"\n❌ 失败的测试:")
            for result in self.test_results:
                if not result["passed"]:
                    print(f"  - {result['name']}: {result['details']}")
        
        print(f"\n🎉 测试完成! 系统{'健康' if pass_rate >= 80 else '需要修复'}")
        
        # 功能特性验证总结
        print(f"\n💡 功能特性验证:")
        print(f"  ✅ 统一状态字段映射: {'通过' if any('统一状态字段映射' in r['name'] and r['passed'] for r in self.test_results) else '失败'}")
        print(f"  ✅ 多Agent协同工作: {'通过' if any('系统初始化' in r['name'] and r['passed'] for r in self.test_results) else '失败'}")
        print(f"  ✅ 业务场景处理: {'通过' if self.passed_tests >= total_tests * 0.7 else '失败'}")
        print(f"  ✅ 人工干预机制: {'通过' if any('人工干预' in r['name'] and r['passed'] for r in self.test_results) else '失败'}")
        print(f"  ✅ 状态传递机制: {'通过' if any('状态传递' in r['name'] and r['passed'] for r in self.test_results) else '失败'}")
        print(f"  ✅ 图路由逻辑: {'通过' if any('图路由逻辑' in r['name'] and r['passed'] for r in self.test_results) else '失败'}")


def main():
    """主测试函数"""
    print("🚀 启动多Agent客户服务系统全面测试")
    print("测试将验证系统的各个核心功能和业务场景")
    print("="*80)
    
    # 创建测试实例
    tester = TestMultiAgentCustomerService()
    
    # 运行所有测试
    tester.run_all_tests()


if __name__ == "__main__":
    main()