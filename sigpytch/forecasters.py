from datetime import datetime
from dateutil.relativedelta import relativedelta
import numpy as np
import pandas as pd
from pandas.tseries.offsets import BDay
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from statsmodels.tsa.arima.model import ARIMA

from .periods import P

class LSTMForecaster():

    def __init__(self, series: pd.Series):
        self.__series = series
        self.model = None

        self.__lags =  P.TDAYS_PER_YEAR
        self.forecast_len = P.TDAYS_PER_YEAR

        self.__scaler = MinMaxScaler(feature_range=(-1, 1))

    def __setup_model(self):
        self.model = Sequential()
        self.model.add(LSTM(self.__lags, input_shape=(self.__lags, 1)))
        self.model.add(Dense(self.forecast_len)) # output layer
        self.model.compile(optimizer="adam", loss="mse")

    def __prepare_data(self, Y: pd.Series, test: bool = False):
        Y = np.array(Y).reshape((-1, 1))
        
        n_fut = self.forecast_len
        n_past = self.__lags
        period = n_fut + n_past

        if test:
            Y_scaled = self.__scaler.transform(Y)
            idx_start = len(Y) - n_fut - n_past
            n_input = 1
        else:
            Y_scaled = self.__scaler.fit_transform(Y)
            train_len = len(Y) - self.forecast_len
            Y_scaled = Y_scaled[ : , :train_len]
            idx_start = 0
            n_input = train_len - self.forecast_len

        X_prep = []
        Y_prep = []
        for i in range(n_input):
            X_prep.append(Y_scaled[idx_start:idx_start+n_past])
            Y_prep.append(Y_scaled[idx_start+n_past:idx_start+period])
            idx_start += 1
        
        X_prep = np.array(X_prep)
        Y_prep = np.array(Y_prep)
        return X_prep, Y_prep

    def __all_dates(self):
      first_date = self.__series.index[0]
      last_date = self.__series.index[-1] + BDay(self.forecast_len)
      return pd.bdate_range(first_date, last_date)
    
    def train(self, lags: int, epochs: int):
        self.__lags = lags

        X_train, Y_train = self.__prepare_data(self.__series)
        if self.model is None: self.__setup_model()
        self.model.summary()
        self.model.fit(X_train, Y_train, epochs=epochs)
        
        X_test, Y_test = self.__prepare_data(self.__series, test=True)
        pred = self.model.predict(X_test)
        pred_unscaled = self.__scaler.inverse_transform(pred).flatten()

        df_test = pd.DataFrame(self.__series)
        empty_list = np.empty(len(df_test))
        empty_list[:] = np.nan
        df_test['Prediction'] = empty_list
        df_test['Prediction'][-self.forecast_len: ] = pred_unscaled
        return df_test
    
    def forecast(self):
        X = self.__series[-self.__lags: ]
        X = np.array(X).reshape((-1, 1))
        X = self.__scaler.transform(X).reshape(X.shape[1], X.shape[0], 1)

        fcst = self.model.predict(X)
        fcst_unscaled = self.__scaler.inverse_transform(fcst).flatten()

        df_fcst = pd.DataFrame(self.__series, index=self.__all_dates())
        empty_list = np.empty(len(df_fcst))
        empty_list[:] = np.nan
        df_fcst['Forecast'] = empty_list
        df_fcst['Forecast'][-self.forecast_len: ] = fcst_unscaled
        return df_fcst

class ARIMAForecaster():
    
    def __init__(self, series: pd.Series):
        self.__series = series
        self.model = None
        self.train = None
        self.test = None
        
    def process_data(self):
        train, test = train_test_split(self.__series, train_size=0.75)
        self.train = train
        self.test = test
        
    def fit_model(self) -> np.array:
        
        # initializes ARIMA model
        model = ARIMA(self.train, order=(5, 2, 2))
        
        fitted_model = model.fit()
        
        preds = fitted_model.forecast(len(self.test)).to_numpy()
        
        self.model = ARIMA(self.__series, order=(5, 2, 2)).fit()
        
        return preds
    
    def validate(self, preds: np.array) -> pd.DataFrame:
        
        df = pd.DataFrame(self.__series)
        df["Predictions"] = pd.Series(preds, index=self.test.index)
        return df
    
    def forecast(self, n: int):
        
        # creates dataframe from observed data
        df = self.__series.to_frame()
        
        # adds prediction column to our datafram
        nulls = np.empty(df.shape[0])
        nulls[:] = np.NaN
        df["Predictions"] = nulls
        
        # forecasts n steps
        fc = self.model.forecast(n, alpha=0.05).to_numpy()
        for i in range(n):
            df.loc[df.index[-1] + pd.Timedelta('1day')] = [np.NaN, fc[i]]
        
        return df
    
    def generate_ci(self, info: pd.DataFrame, n: int, alpha:int =0.05):

        # creates copy of the dataframe
        df = info.copy()
        
        # generates confidence interval
        
        ci = self.model.get_forecast(n).conf_int(alpha=alpha)
        ci.index = info.index[-n:]
        
        df["Lower Bound"] = ci["lower Close"]
        df["Upper Bound"] = ci["upper Close"]  
        
        return df