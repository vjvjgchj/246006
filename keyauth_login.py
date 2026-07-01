import os
import sys
import hashlib
import io
import contextlib
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QHBoxLayout, QApplication, QCheckBox
)
from PySide6.QtCore import Qt
from keyauth import api

# 需要用户自己去 https://keyauth.cc/app/ 注册并填入以下信息
def getchecksum():
    md5_hash = hashlib.md5()
    with open(os.path.abspath(__file__), "rb") as f:
        md5_hash.update(f.read())
    return md5_hash.hexdigest()

def init_keyauth():
    return api(
        name = "246006's Application",
        ownerid = "kweDXvWwXS",
        version = "1.0",
        hash_to_check = getchecksum()
    )

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("卡密验证 - KeyAuth")
        self.setFixedSize(350, 170)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        # 提示标签
        self.info_label = QLabel("请输入您的卡密以继续：", self)
        layout.addWidget(self.info_label)

        # 卡密输入框
        self.key_input = QLineEdit(self)
        self.key_input.setPlaceholderText("XXXXX-XXXXX-XXXXX-XXXXX")
        layout.addWidget(self.key_input)

        self.code_toggle = QCheckBox("使用 2FA code", self)
        self.code_toggle.toggled.connect(self.toggle_2fa_input)
        layout.addWidget(self.code_toggle)

        # 2FA 验证码输入框，默认隐藏；未启用时无需填写
        self.code_input = QLineEdit(self)
        self.code_input.setPlaceholderText("2FA code (未启用可留空)")
        self.code_input.setVisible(False)
        layout.addWidget(self.code_input)

        # 按钮布局
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("验证", self)
        self.login_btn.clicked.connect(self.verify_key)
        self.quit_btn = QPushButton("退出", self)
        self.quit_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.quit_btn)

        layout.addLayout(btn_layout)

    def toggle_2fa_input(self, checked):
        self.code_input.setVisible(checked)
        self.setFixedSize(350, 200 if checked else 170)

    def verify_key(self):
        key = self.key_input.text().strip()
        code = self.code_input.text().strip()
        if not key:
            QMessageBox.warning(self, "错误", "卡密不能为空！")
            return

        self.login_btn.setEnabled(False)
        self.info_label.setText("正在验证...")
        QApplication.processEvents()

        try:
            # 临时拦截 os._exit 防止 KeyAuth 验证失败时直接闪退
            original_exit = os._exit
            captured_stdout = io.StringIO()
            def intercepted_exit(code):
                raise Exception(f"卡密无效或验证失败 (退出代码 {code})")
            os._exit = intercepted_exit

            try:
                with contextlib.redirect_stdout(captured_stdout):
                    # 初始化并调用 KeyAuth 的 license 验证
                    keyauthapp = init_keyauth()
                    keyauthapp.license(key, code)
            finally:
                # 恢复原版 os._exit
                os._exit = original_exit

            # 如果能走到这里，说明验证成功
            QMessageBox.information(self, "成功", "验证成功！欢迎使用。")
            self.accept()
        except Exception as e:
            sdk_output = captured_stdout.getvalue().strip() if "captured_stdout" in locals() else ""
            detail = f"{str(e)}\n\nKeyAuth 输出：{sdk_output}" if sdk_output else str(e)
            QMessageBox.critical(self, "错误", f"验证发生异常：{detail}")
            self.login_btn.setEnabled(True)
            self.info_label.setText("请输入您的卡密以继续：")


def show_login():
    """
    显示登录框，如果成功返回 True，失败或关闭返回 False
    """
    dialog = LoginDialog()
    result = dialog.exec()
    return result == QDialog.Accepted

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if show_login():
        print("卡密验证通过，进入主程序。")
    else:
        print("未通过验证，退出。")
