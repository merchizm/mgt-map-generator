#include <QStylePlugin>
#include <QApplication>
#include <QResource>

#include <oclero/qlementine/style/QlementineStyle.hpp>

class MgtQlementineStyle final : public oclero::qlementine::QlementineStyle {
  Q_OBJECT
  Q_PROPERTY(bool darkTheme READ darkTheme WRITE setDarkTheme)

public:
  explicit MgtQlementineStyle(QObject* parent = nullptr)
    : oclero::qlementine::QlementineStyle(parent) {
    Q_INIT_RESOURCE(mgt_qlementine_style_plugin);
    setDarkTheme(false);
  }

  bool darkTheme() const {
    return _darkTheme;
  }

  void setDarkTheme(bool darkTheme) {
    if (_darkTheme == darkTheme && _initialized) {
      return;
    }

    _darkTheme = darkTheme;
    _initialized = true;
    setThemeJsonPath(_darkTheme ? QStringLiteral(":/mgt_qlementine/themes/dark.json")
                                : QStringLiteral(":/mgt_qlementine/themes/light.json"));
    if (qApp) {
      qApp->setPalette(standardPalette());
    }
    triggerCompleteRepaint();
  }

private:
  bool _darkTheme{ false };
  bool _initialized{ false };
};

class MgtQlementineStylePlugin final : public QStylePlugin {
  Q_OBJECT
  Q_PLUGIN_METADATA(IID "org.qt-project.Qt.QStyleFactoryInterface" FILE "mgt_qlementine_style_plugin.json")

public:
  QStyle* create(const QString& key) override {
    if (key.compare(QStringLiteral("Qlementine"), Qt::CaseInsensitive) == 0) {
      return new MgtQlementineStyle();
    }
    return nullptr;
  }
};

#include "mgt_qlementine_style_plugin.moc"
